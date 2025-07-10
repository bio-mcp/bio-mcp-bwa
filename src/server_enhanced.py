"""
Enhanced BLAST MCP server with intelligent tool detection.

This server can automatically detect and use BLAST tools from:
- Native installations (PATH)
- Environment Modules
- Lmod modules
- Singularity containers
- Docker containers

Environment variables for configuration:
- BIO_MCP_EXECUTION_MODE: Force specific mode (native, module, lmod, singularity, docker)
- BIO_MCP_PREFERRED_MODES: Comma-separated list of preferred modes
- BIO_MCP_MODULE_NAMES: Comma-separated list of BLAST module names to try
- BIO_MCP_CONTAINER_IMAGE: Container image to use for BLAST
- BIO_MCP_FORCE_CONTAINER: Set to 'true' to force container usage
"""

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Literal

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent, ErrorContent
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .tool_detection import ToolDetector, ToolConfig, ExecutionMode, ToolInfo


logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    max_file_size: int = Field(default=100_000_000, description="Maximum input file size in bytes")
    temp_dir: Optional[str] = Field(default=None, description="Temporary directory for processing")
    timeout: int = Field(default=300, description="Command timeout in seconds")
    
    # Tool execution mode settings
    execution_mode: Optional[str] = Field(default=None, description="Force specific execution mode")
    preferred_modes: str = Field(default="native,module,lmod,singularity,docker", description="Preferred execution modes")
    
    # Module settings
    module_names: str = Field(default="blast,blast+,ncbi-blast+", description="BLAST module names to try")
    
    # Container settings
    container_image: str = Field(default="biocontainers/blast:2.15.0", description="Container image for BLAST")
    force_container: bool = Field(default=False, description="Force container usage")
    
    class Config:
        env_prefix = "BIO_MCP_"


class BlastServer:
    def __init__(self, settings: Optional[ServerSettings] = None):
        self.settings = settings or ServerSettings()
        self.server = Server("bio-mcp-blast")
        self.detector = ToolDetector(logger)
        self.tool_config = ToolConfig.from_env()
        
        # Cache for detected tools
        self.blastn_info = None
        self.blastp_info = None
        self.makeblastdb_info = None
        
        self._setup_handlers()
        
    async def _detect_blast_tool(self, tool_name: str) -> ToolInfo:
        """Detect the best available execution mode for a BLAST tool."""
        # Parse settings
        force_mode = None
        if self.settings.execution_mode:
            try:
                force_mode = ExecutionMode(self.settings.execution_mode.lower())
            except ValueError:
                logger.warning(f"Invalid execution mode: {self.settings.execution_mode}")
        
        # Override with container if forced
        if self.settings.force_container:
            force_mode = ExecutionMode.SINGULARITY  # Try Singularity first, then Docker
        
        preferred_modes = []
        for mode_str in self.settings.preferred_modes.split(","):
            try:
                mode = ExecutionMode(mode_str.strip().lower())
                preferred_modes.append(mode)
            except ValueError:
                logger.warning(f"Invalid preferred mode: {mode_str}")
        
        module_names = [name.strip() for name in self.settings.module_names.split(",")]
        
        # Detect tool
        tool_info = self.detector.detect_tool(
            tool_name=tool_name,
            module_names=module_names,
            container_image=self.settings.container_image,
            preferred_modes=preferred_modes or None,
            force_mode=force_mode
        )
        
        return tool_info
    
    async def _get_blastn_info(self) -> ToolInfo:
        """Get BLASTN tool information."""
        if self.blastn_info is None:
            self.blastn_info = await self._detect_blast_tool("blastn")
        return self.blastn_info
    
    async def _get_blastp_info(self) -> ToolInfo:
        """Get BLASTP tool information."""
        if self.blastp_info is None:
            self.blastp_info = await self._detect_blast_tool("blastp")
        return self.blastp_info
    
    async def _get_makeblastdb_info(self) -> ToolInfo:
        """Get makeblastdb tool information."""
        if self.makeblastdb_info is None:
            self.makeblastdb_info = await self._detect_blast_tool("makeblastdb")
        return self.makeblastdb_info
        
    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="blastn",
                    description="Nucleotide-nucleotide BLAST search with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string", 
                                "description": "Path to query FASTA file or sequence string"
                            },
                            "database": {
                                "type": "string",
                                "description": "Path to BLAST database or database name"
                            },
                            "output_format": {
                                "type": "string",
                                "description": "Output format (0-18)",
                                "default": "6"
                            },
                            "evalue": {
                                "type": "number",
                                "description": "E-value threshold",
                                "default": 0.001
                            },
                            "max_target_seqs": {
                                "type": "integer",
                                "description": "Maximum number of target sequences",
                                "default": 10
                            },
                            "num_threads": {
                                "type": "integer",
                                "description": "Number of threads",
                                "default": 1
                            }
                        },
                        "required": ["query", "database"]
                    }
                ),
                Tool(
                    name="blastp",
                    description="Protein-protein BLAST search with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string", 
                                "description": "Path to query FASTA file or sequence string"
                            },
                            "database": {
                                "type": "string",
                                "description": "Path to BLAST database or database name"
                            },
                            "output_format": {
                                "type": "string",
                                "description": "Output format (0-18)",
                                "default": "6"
                            },
                            "evalue": {
                                "type": "number",
                                "description": "E-value threshold",
                                "default": 0.001
                            },
                            "max_target_seqs": {
                                "type": "integer",
                                "description": "Maximum number of target sequences",
                                "default": 10
                            },
                            "num_threads": {
                                "type": "integer",
                                "description": "Number of threads",
                                "default": 1
                            }
                        },
                        "required": ["query", "database"]
                    }
                ),
                Tool(
                    name="makeblastdb",
                    description="Create BLAST database with intelligent tool detection",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": "Path to input FASTA file"
                            },
                            "dbtype": {
                                "type": "string",
                                "description": "Database type (nucl or prot)",
                                "enum": ["nucl", "prot"]
                            },
                            "title": {
                                "type": "string",
                                "description": "Database title"
                            },
                            "parse_seqids": {
                                "type": "boolean",
                                "description": "Parse sequence IDs",
                                "default": False
                            }
                        },
                        "required": ["input", "dbtype"]
                    }
                ),
                Tool(
                    name="blast_info",
                    description="Get information about BLAST tool detection and execution mode",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> list[TextContent | ImageContent | ErrorContent]:
            if name == "blastn":
                return await self._run_blastn(arguments)
            elif name == "blastp":
                return await self._run_blastp(arguments)
            elif name == "makeblastdb":
                return await self._run_makeblastdb(arguments)
            elif name == "blast_info":
                return await self._get_blast_info()
            else:
                return [ErrorContent(text=f"Unknown tool: {name}")]
    
    async def _get_blast_info(self) -> list[TextContent]:
        """Get information about BLAST tool detection."""
        info = {
            "execution_settings": {
                "execution_mode": self.settings.execution_mode,
                "preferred_modes": self.settings.preferred_modes.split(","),
                "module_names": self.settings.module_names.split(","),
                "container_image": self.settings.container_image,
                "force_container": self.settings.force_container
            },
            "detected_tools": {}
        }
        
        # Detect each tool
        for tool_name in ["blastn", "blastp", "makeblastdb"]:
            tool_info = await self._detect_blast_tool(tool_name)
            info["detected_tools"][tool_name] = {
                "mode": tool_info.mode.value,
                "path": tool_info.path,
                "version": tool_info.version,
                "module_name": tool_info.module_name,
                "container_image": tool_info.container_image,
                "available": tool_info.mode != ExecutionMode.UNAVAILABLE
            }
        
        return [TextContent(text=json.dumps(info, indent=2))]
    
    async def _run_blastn(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run BLASTN with intelligent tool detection."""
        return await self._run_blast_tool("blastn", arguments)
    
    async def _run_blastp(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run BLASTP with intelligent tool detection."""
        return await self._run_blast_tool("blastp", arguments)
    
    async def _run_blast_tool(self, tool_name: str, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run a BLAST tool with intelligent execution mode detection."""
        try:
            # Get tool info
            tool_info = await self._detect_blast_tool(tool_name)
            
            if tool_info.mode == ExecutionMode.UNAVAILABLE:
                return [ErrorContent(text=f"{tool_name} is not available in any execution mode")]
            
            # Handle query input
            query = arguments["query"]
            database = arguments["database"]
            
            # Create temporary directory for processing
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                tmpdir_path = Path(tmpdir)
                
                # Handle query (file or sequence string)
                if Path(query).exists():
                    # It's a file path
                    query_path = Path(query)
                    if query_path.stat().st_size > self.settings.max_file_size:
                        return [ErrorContent(text=f"Query file too large. Maximum size: {self.settings.max_file_size} bytes")]
                    
                    # Copy to temp directory
                    temp_query = tmpdir_path / query_path.name
                    temp_query.write_bytes(query_path.read_bytes())
                    query_arg = str(temp_query)
                else:
                    # It's a sequence string
                    temp_query = tmpdir_path / "query.fasta"
                    temp_query.write_text(query)
                    query_arg = str(temp_query)
                
                # Build command arguments
                tool_args = [
                    "-query", query_arg,
                    "-db", database,
                    "-outfmt", str(arguments.get("output_format", 6)),
                    "-evalue", str(arguments.get("evalue", 0.001)),
                    "-max_target_seqs", str(arguments.get("max_target_seqs", 10)),
                    "-num_threads", str(arguments.get("num_threads", 1))
                ]
                
                # Get the complete command based on execution mode
                cmd = self.detector.get_execution_command(tool_info, tool_args)
                
                logger.info(f"Executing {tool_name} via {tool_info.mode.value}: {' '.join(cmd)}")
                
                # Execute command
                if tool_info.mode in [ExecutionMode.MODULE, ExecutionMode.LMOD]:
                    # Module commands need to be executed in shell
                    shell_cmd = " ".join(cmd)
                    process = await asyncio.create_subprocess_shell(
                        shell_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=tmpdir
                    )
                else:
                    # Direct execution for native, container modes
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=tmpdir
                    )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return [ErrorContent(text=f"Command timed out after {self.settings.timeout} seconds")]
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"BLAST command failed: {stderr.decode()}")]
                
                # Return results
                output = stdout.decode()
                return [TextContent(text=output)]
                
        except Exception as e:
            logger.error(f"Error running {tool_name}: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def _run_makeblastdb(self, arguments: dict) -> list[TextContent | ErrorContent]:
        """Run makeblastdb with intelligent tool detection."""
        try:
            # Get tool info
            tool_info = await self._get_makeblastdb_info()
            
            if tool_info.mode == ExecutionMode.UNAVAILABLE:
                return [ErrorContent(text="makeblastdb is not available in any execution mode")]
            
            # Validate input file
            input_path = Path(arguments["input"])
            if not input_path.exists():
                return [ErrorContent(text=f"Input file not found: {input_path}")]
            
            if input_path.stat().st_size > self.settings.max_file_size:
                return [ErrorContent(text=f"Input file too large. Maximum size: {self.settings.max_file_size} bytes")]
            
            # Create temporary directory for processing
            with tempfile.TemporaryDirectory(dir=self.settings.temp_dir) as tmpdir:
                tmpdir_path = Path(tmpdir)
                
                # Copy input file to temp directory
                temp_input = tmpdir_path / input_path.name
                temp_input.write_bytes(input_path.read_bytes())
                
                # Build command arguments
                tool_args = [
                    "-in", str(temp_input),
                    "-dbtype", arguments["dbtype"]
                ]
                
                if "title" in arguments:
                    tool_args.extend(["-title", arguments["title"]])
                
                if arguments.get("parse_seqids", False):
                    tool_args.append("-parse_seqids")
                
                # Get the complete command based on execution mode
                cmd = self.detector.get_execution_command(tool_info, tool_args)
                
                logger.info(f"Executing makeblastdb via {tool_info.mode.value}: {' '.join(cmd)}")
                
                # Execute command
                if tool_info.mode in [ExecutionMode.MODULE, ExecutionMode.LMOD]:
                    # Module commands need to be executed in shell
                    shell_cmd = " ".join(cmd)
                    process = await asyncio.create_subprocess_shell(
                        shell_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=tmpdir
                    )
                else:
                    # Direct execution for native, container modes
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=tmpdir
                    )
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(),
                        timeout=self.settings.timeout
                    )
                except asyncio.TimeoutError:
                    process.kill()
                    return [ErrorContent(text=f"Command timed out after {self.settings.timeout} seconds")]
                
                if process.returncode != 0:
                    return [ErrorContent(text=f"makeblastdb failed: {stderr.decode()}")]
                
                # Return results
                output = stdout.decode()
                return [TextContent(text=f"Database created successfully\\n{output}")]
                
        except Exception as e:
            logger.error(f"Error running makeblastdb: {e}", exc_info=True)
            return [ErrorContent(text=f"Error: {str(e)}")]
    
    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream)


async def main():
    logging.basicConfig(level=logging.INFO)
    server = BlastServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())