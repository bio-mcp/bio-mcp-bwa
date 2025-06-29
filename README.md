# bio-mcp-bwa

MCP (Model Context Protocol) server for the BWA (Burrows-Wheeler Aligner) sequence alignment tool.

## Overview

This MCP server provides access to BWA functionality, allowing AI assistants to perform alignment of short and long sequencing reads to a reference genome.

## Features

- **bwa_index**: Create an index for a reference genome.
- **bwa_mem**: Align reads using the BWA-MEM algorithm.
- **bwa_aln**: Find SA coordinates with the BWA-backtrack algorithm.
- **bwa_samse**: Generate single-end alignments in SAM format.
- **bwa_sampe**: Generate paired-end alignments in SAM format.
- Support for large reference genomes and read files.

## Installation

### Prerequisites

- Python 3.9+
- BWA installed (`bwa`)

### Install BWA

```bash
# macOS
brew install bwa

# Ubuntu/Debian
sudo apt-get install bwa

# From conda
conda install -c bioconda bwa
```

### Install the MCP server

```bash
git clone https://github.com/your-username/bio-mcp-bwa
cd bio-mcp-bwa
pip install -e .
```

## Configuration

Add to your MCP client configuration (e.g., Claude Desktop `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bio-bwa": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/bio-mcp-bwa"
    }
  }
}
```

### Environment Variables

- `BIO_MCP_MAX_FILE_SIZE`: Maximum input file size in bytes (default: 50GB)
- `BIO_MCP_TIMEOUT`: Command timeout in seconds (default: 3600)
- `BIO_MCP_BWA_PATH`: Path to BWA executable (default: finds in PATH)
- `BIO_MCP_TEMP_DIR`: Temporary directory for processing

## Usage

Once configured, the AI assistant can use the following tools:

### `bwa_index` - Create BWA Index

Create a BWA index for a reference genome.

**Parameters:**
- `reference_fasta` (required): Path to the reference FASTA file.
- `algorithm`: Indexing algorithm (`bwtsw` or `is`). Defaults to `bwtsw` for genomes >2GB.

### `bwa_mem` - Align with BWA-MEM

Align reads using the BWA-MEM algorithm.

**Parameters:**
- `reference` (required): Path to the indexed reference genome.
- `reads1` (required): Path to the first reads file (FASTQ).
- `reads2`: Path to the second reads file for paired-end alignment.
- `threads`: Number of threads to use (default: 4).
- `min_seed_length`: Minimum seed length (default: 19).
- `band_width`: Band width for banded alignment (default: 100).
- `read_group`: Read group header line.

### `bwa_aln` - Find SA Coordinates

Find SA coordinates with the BWA-backtrack algorithm.

**Parameters:**
- `reference` (required): Path to the indexed reference genome.
- `reads` (required): Path to the reads file (FASTQ).
- `threads`: Number of threads to use (default: 4).
- `max_mismatches`: Maximum number of mismatches (default: 4).
- `max_gap_opens`: Maximum number of gap opens (default: 1).

### `bwa_samse` - Generate Single-End SAM

Generate alignments in SAM format for single-end reads.

**Parameters:**
- `reference` (required): Path to the indexed reference genome.
- `sai_file` (required): Path to the .sai file from `bwa_aln`.
- `reads` (required): Path to the original reads file.

### `bwa_sampe` - Generate Paired-End SAM

Generate alignments in SAM format for paired-end reads.

**Parameters:**
- `reference` (required): Path to the indexed reference genome.
- `sai_file1` (required): Path to the .sai file for read 1.
- `sai_file2` (required): Path to the .sai file for read 2.
- `reads1` (required): Path to the reads file 1.
- `reads2` (required): Path to the reads file 2.

## Examples

### Index a reference genome
```
Create a BWA index for the file hg38.fasta.
```

### Align paired-end reads
```
Align the paired-end reads from r1.fastq and r2.fastq to the hg38 reference genome using BWA-MEM.
```

## Development

### Running tests

```bash
pytest tests/
```

### Building Docker image

```bash
docker build -t bio-mcp-bwa .
```

## License

MIT License
