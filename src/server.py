import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ErrorContent
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = 50_000_000_000  # 50GB for large FASTQ files
    temp_dir: Optional[str] = None
    timeout: int = 3600  # 1 hour for alignment
    bwa_path: str = "bwa"
    
    class Config:
        env_prefix = "BIO_MCP_"


class BwaServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-bwa")
        self._setup_handlers()
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="bwa_index",
                    description="Create BWA index for reference genome",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference_fasta": {
                                "type": "string",
                                "description": "Path to reference FASTA file"
                            },
                            "algorithm": {
                                "type": "string",
                                "enum": ["bwtsw", "is"],
                                "default": "bwtsw",
                                "description": "Indexing algorithm (bwtsw for >2GB genomes)"
                            }
                        },
                        "required": ["reference_fasta"]
                    }
                ),
                Tool(
                    name="bwa_mem",
                    description="Align reads using BWA-MEM algorithm",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Path to indexed reference genome"
                            },
                            "reads1": {
                                "type": "string",
                                "description": "Path to first reads file (FASTQ)"
                            },
                            "reads2": {
                                "type": "string",
                                "description": "Path to second reads file for paired-end"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 4,
                                "description": "Number of threads"
                            },
                            "min_seed_length": {
                                "type": "integer",
                                "default": 19,
                                "description": "Minimum seed length"
                            },
                            "band_width": {
                                "type": "integer",
                                "default": 100,
                                "description": "Band width for banded alignment"
                            },
                            "read_group": {
                                "type": "string",
                                "description": "Read group header line (e.g., '@RG\\tID:sample1\\tSM:sample1')"
                            }
                        },
                        "required": ["reference", "reads1"]
                    }
                ),
                Tool(
                    name="bwa_aln",
                    description="Find SA coordinates with BWA-backtrack algorithm",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Path to indexed reference genome"
                            },
                            "reads": {
                                "type": "string",
                                "description": "Path to reads file (FASTQ)"
                            },
                            "threads": {
                                "type": "integer",
                                "default": 4
                            },
                            "max_mismatches": {
                                "type": "integer",
                                "default": 4,
                                "description": "Maximum number of mismatches"
                            },
                            "max_gap_opens": {
                                "type": "integer",
                                "default": 1,
                                "description": "Maximum number of gap opens"
                            }
                        },
                        "required": ["reference", "reads"]
                    }
                ),
                Tool(
                    name="bwa_samse",
                    description="Generate alignments in SAM format (single-end)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Path to indexed reference genome"
                            },
                            "sai_file": {
                                "type": "string",
                                "description": "Path to .sai file from bwa aln"
                            },
                            "reads": {
                                "type": "string",
                                "description": "Path to original reads file"
                            }
                        },
                        "required": ["reference", "sai_file", "reads"]
                    }
                ),
                Tool(
                    name="bwa_sampe",
                    description="Generate alignments in SAM format (paired-end)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "reference": {
                                "type": "string",
                                "description": "Path to indexed reference genome"
                            },
                            "sai_file1": {
                                "type": "string",
                                "description": "Path to .sai file for read 1"
                            },
                            "sai_file2": {
                                "type": "string",
                                "description": "Path to .sai file for read 2"
                            },
                            "reads1": {
                                "type": "string",
                                "description": "Path to reads file 1"
                            },
                            "reads2": {
                                "type": "string",
                                "description": "Path to reads file 2"
                            }
                        },
                        "required": ["reference", "sai_file1", "sai_file2", "reads1", "reads2"]
                    }
                ),
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ErrorContent]:
            handlers = {
                "bwa_index": self._run_index,
                "bwa_mem": self._run_mem,
                "bwa_aln": self._run_aln,
                "bwa_samse": self._run_samse,
                "bwa_sampe": self._run_sampe,
            }
            
            handler = handlers.get(name)
            if handler:
                return await handler(arguments)
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _run_index(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            reference_fasta = Path(arguments["reference_fasta"])
            if not reference_fasta.exists():
                return [ErrorContent(text=f"Reference file not found: {reference_fasta}")]
            
            # Check file size for algorithm choice
            file_size = reference_fasta.stat().st_size
            algorithm = arguments.get("algorithm", "bwtsw" if file_size > 2_000_000_000 else "is")
            
            cmd = [self.settings.bwa_path, "index", "-a", algorithm, str(reference_fasta)]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.settings.timeout
            )
            
            if process.returncode != 0:
                return [ErrorContent(text=f"BWA index failed: {stderr.decode()}")]
            
            # List created index files
            index_files = []
            for suffix in ['.amb', '.ann', '.bwt', '.pac', '.sa']:
                index_file = reference_fasta.with_suffix(reference_fasta.suffix + suffix)
                if index_file.exists():
                    index_files.append(str(index_file))
            
            return [TextContent(
                text=f"BWA index created successfully!\n\n"
                     f"Reference: {reference_fasta}\n"
                     f"Algorithm: {algorithm}\n"
                     f"Index files created:\n" + '\n'.join(f"  • {f}" for f in index_files)
            )]
            
        except Exception as e:
            logger.error(f"Error in BWA index: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_mem(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            reference = Path(arguments["reference"])
            reads1 = Path(arguments["reads1"])
            
            if not reference.exists():
                return [ErrorContent(text=f"Reference not found: {reference}")]
            if not reads1.exists():
                return [ErrorContent(text=f"Reads file not found: {reads1}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_sam = Path(tmpdir) / "alignment.sam"
                
                cmd = [
                    self.settings.bwa_path, "mem",
                    "-t", str(arguments.get("threads", 4)),
                    "-k", str(arguments.get("min_seed_length", 19)),
                    "-w", str(arguments.get("band_width", 100))
                ]
                
                # Add read group if provided
                if arguments.get("read_group"):
                    cmd.extend(["-R", arguments["read_group"]])
                
                cmd.append(str(reference))
                cmd.append(str(reads1))
                
                # Add second reads file if paired-end
                if arguments.get("reads2"):
                    reads2 = Path(arguments["reads2"])
                    if reads2.exists():
                        cmd.append(str(reads2))
                
                # Redirect output to file
                with open(output_sam, 'w') as f:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=f,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    _, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"BWA mem failed: {stderr.decode()}")]
                
                # Get alignment statistics
                output_size = output_sam.stat().st_size
                
                # Count alignments quickly
                with open(output_sam) as f:
                    total_lines = sum(1 for line in f if not line.startswith('@'))
                
                return [TextContent(
                    text=f"BWA-MEM alignment completed!\n\n"
                         f"Output file: {output_sam}\n"
                         f"Output size: {output_size:,} bytes\n"
                         f"Alignment records: {total_lines:,}\n"
                         f"Threads used: {arguments.get('threads', 4)}\n"
                         f"Paired-end: {'Yes' if arguments.get('reads2') else 'No'}"
                )]
                
        except Exception as e:
            logger.error(f"Error in BWA mem: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_aln(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            reference = Path(arguments["reference"])
            reads = Path(arguments["reads"])
            
            if not reference.exists():
                return [ErrorContent(text=f"Reference not found: {reference}")]
            if not reads.exists():
                return [ErrorContent(text=f"Reads file not found: {reads}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_sai = Path(tmpdir) / "alignment.sai"
                
                cmd = [
                    self.settings.bwa_path, "aln",
                    "-t", str(arguments.get("threads", 4)),
                    "-n", str(arguments.get("max_mismatches", 4)),
                    "-o", str(arguments.get("max_gap_opens", 1)),
                    str(reference),
                    str(reads)
                ]
                
                with open(output_sai, 'wb') as f:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=f,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    _, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"BWA aln failed: {stderr.decode()}")]
                
                output_size = output_sai.stat().st_size
                
                return [TextContent(
                    text=f"BWA aln completed!\n\n"
                         f"Output SAI file: {output_sai}\n"
                         f"Output size: {output_size:,} bytes\n"
                         f"Use bwa_samse/sampe to convert to SAM format"
                )]
                
        except Exception as e:
            logger.error(f"Error in BWA aln: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_samse(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            reference = Path(arguments["reference"])
            sai_file = Path(arguments["sai_file"])
            reads = Path(arguments["reads"])
            
            for file_path in [reference, sai_file, reads]:
                if not file_path.exists():
                    return [ErrorContent(text=f"File not found: {file_path}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_sam = Path(tmpdir) / "alignment.sam"
                
                cmd = [
                    self.settings.bwa_path, "samse",
                    str(reference),
                    str(sai_file),
                    str(reads)
                ]
                
                with open(output_sam, 'w') as f:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=f,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    _, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"BWA samse failed: {stderr.decode()}")]
                
                output_size = output_sam.stat().st_size
                
                return [TextContent(
                    text=f"BWA samse completed!\n\n"
                         f"Output SAM file: {output_sam}\n"
                         f"Output size: {output_size:,} bytes"
                )]
                
        except Exception as e:
            logger.error(f"Error in BWA samse: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_sampe(self, arguments: dict) -> list[TextContent | ErrorContent]:
        try:
            reference = Path(arguments["reference"])
            sai_file1 = Path(arguments["sai_file1"])
            sai_file2 = Path(arguments["sai_file2"])
            reads1 = Path(arguments["reads1"])
            reads2 = Path(arguments["reads2"])
            
            for file_path in [reference, sai_file1, sai_file2, reads1, reads2]:
                if not file_path.exists():
                    return [ErrorContent(text=f"File not found: {file_path}")]
            
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                output_sam = Path(tmpdir) / "alignment.sam"
                
                cmd = [
                    self.settings.bwa_path, "sampe",
                    str(reference),
                    str(sai_file1),
                    str(sai_file2),
                    str(reads1),
                    str(reads2)
                ]
                
                with open(output_sam, 'w') as f:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=f,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    _, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"BWA sampe failed: {stderr.decode()}")]
                
                output_size = output_sam.stat().st_size
                
                return [TextContent(
                    text=f"BWA sampe completed!\n\n"
                         f"Output SAM file: {output_sam}\n"
                         f"Output size: {output_size:,} bytes"
                )]
                
        except Exception as e:
            logger.error(f"Error in BWA sampe: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream)


async def main():
    logging.basicConfig(level=logging.INFO)
    server = BwaServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())