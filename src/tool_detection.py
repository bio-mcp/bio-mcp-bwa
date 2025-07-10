"""
Tool detection utility for Bio-MCP servers.

This module provides intelligent detection of bioinformatics tools across different
deployment environments including HPC clusters, containers, and native installations.
"""

import os
import subprocess
import shutil
import logging
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pydantic import BaseModel


class ExecutionMode(str, Enum):
    """Execution mode for bioinformatics tools."""
    NATIVE = "native"           # Tool available in PATH
    MODULE = "module"           # Tool available via Environment Modules
    LMOD = "lmod"              # Tool available via Lmod
    SINGULARITY = "singularity" # Tool available via Singularity container
    DOCKER = "docker"          # Tool available via Docker container
    UNAVAILABLE = "unavailable" # Tool not available


@dataclass
class ToolInfo:
    """Information about a detected tool."""
    name: str
    mode: ExecutionMode
    path: Optional[str] = None
    version: Optional[str] = None
    module_name: Optional[str] = None
    container_image: Optional[str] = None
    command_prefix: List[str] = None
    
    def __post_init__(self):
        if self.command_prefix is None:
            self.command_prefix = []


class ToolDetector:
    """Detects available bioinformatics tools across different environments."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self._module_system = None
        self._detect_module_system()
    
    def _detect_module_system(self):
        """Detect which module system is available."""
        if shutil.which("module"):
            try:
                result = subprocess.run(
                    ["module", "avail"], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                self._module_system = "module"
                self.logger.debug("Environment Modules detected")
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                pass
        
        if not self._module_system and shutil.which("ml"):
            try:
                result = subprocess.run(
                    ["ml", "avail"], 
                    capture_output=True, 
                    text=True, 
                    timeout=10
                )
                self._module_system = "lmod"
                self.logger.debug("Lmod detected")
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                pass
    
    def _check_native_tool(self, tool_name: str) -> Optional[ToolInfo]:
        """Check if tool is available natively in PATH."""
        tool_path = shutil.which(tool_name)
        if not tool_path:
            return None
        
        # Try to get version
        version = None
        for version_flag in ["--version", "-v", "-V", "version"]:
            try:
                result = subprocess.run(
                    [tool_path, version_flag],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    version = result.stdout.strip().split('\n')[0]
                    break
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                continue
        
        return ToolInfo(
            name=tool_name,
            mode=ExecutionMode.NATIVE,
            path=tool_path,
            version=version,
            command_prefix=[]
        )
    
    def _check_module_tool(self, tool_name: str, module_names: List[str]) -> Optional[ToolInfo]:
        """Check if tool is available via module system."""
        if not self._module_system:
            return None
        
        module_cmd = "module" if self._module_system == "module" else "ml"
        
        for module_name in module_names:
            try:
                # Check if module is available
                result = subprocess.run(
                    [module_cmd, "avail", module_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if module_name.lower() in result.stderr.lower() or module_name.lower() in result.stdout.lower():
                    # Module is available
                    mode = ExecutionMode.MODULE if self._module_system == "module" else ExecutionMode.LMOD
                    
                    return ToolInfo(
                        name=tool_name,
                        mode=mode,
                        module_name=module_name,
                        command_prefix=[module_cmd, "load", module_name, "&&"]
                    )
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                continue
        
        return None
    
    def _check_singularity_tool(self, tool_name: str, container_image: str) -> Optional[ToolInfo]:
        """Check if tool is available via Singularity."""
        if not shutil.which("singularity"):
            return None
        
        # Check if container image exists or can be built
        container_path = f"{tool_name}.sif"
        
        return ToolInfo(
            name=tool_name,
            mode=ExecutionMode.SINGULARITY,
            container_image=container_image,
            command_prefix=["singularity", "exec", container_path]
        )
    
    def _check_docker_tool(self, tool_name: str, container_image: str) -> Optional[ToolInfo]:
        """Check if tool is available via Docker."""
        if not shutil.which("docker"):
            return None
        
        try:
            # Check if Docker daemon is running
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return None
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return None
        
        return ToolInfo(
            name=tool_name,
            mode=ExecutionMode.DOCKER,
            container_image=container_image,
            command_prefix=["docker", "run", "--rm", "-v", "${PWD}:/data", "-w", "/data", container_image]
        )
    
    def detect_tool(
        self,
        tool_name: str,
        module_names: Optional[List[str]] = None,
        container_image: Optional[str] = None,
        preferred_modes: Optional[List[ExecutionMode]] = None,
        force_mode: Optional[ExecutionMode] = None
    ) -> ToolInfo:
        """
        Detect the best available execution mode for a tool.
        
        Args:
            tool_name: Name of the tool to detect
            module_names: List of possible module names to check
            container_image: Container image name for fallback
            preferred_modes: Preferred execution modes in order
            force_mode: Force a specific execution mode
            
        Returns:
            ToolInfo object with detected information
        """
        if module_names is None:
            module_names = [tool_name]
        
        if preferred_modes is None:
            preferred_modes = [
                ExecutionMode.NATIVE,
                ExecutionMode.MODULE,
                ExecutionMode.LMOD,
                ExecutionMode.SINGULARITY,
                ExecutionMode.DOCKER
            ]
        
        # If user forces a specific mode, only try that
        if force_mode:
            preferred_modes = [force_mode]
        
        for mode in preferred_modes:
            tool_info = None
            
            if mode == ExecutionMode.NATIVE:
                tool_info = self._check_native_tool(tool_name)
            elif mode in [ExecutionMode.MODULE, ExecutionMode.LMOD]:
                tool_info = self._check_module_tool(tool_name, module_names)
            elif mode == ExecutionMode.SINGULARITY and container_image:
                tool_info = self._check_singularity_tool(tool_name, container_image)
            elif mode == ExecutionMode.DOCKER and container_image:
                tool_info = self._check_docker_tool(tool_name, container_image)
            
            if tool_info:
                self.logger.info(f"Tool {tool_name} detected via {tool_info.mode.value}")
                return tool_info
        
        # Tool not available in any mode
        self.logger.warning(f"Tool {tool_name} not available in any execution mode")
        return ToolInfo(
            name=tool_name,
            mode=ExecutionMode.UNAVAILABLE
        )
    
    def get_execution_command(self, tool_info: ToolInfo, args: List[str]) -> List[str]:
        """
        Generate the full command to execute a tool.
        
        Args:
            tool_info: Tool information from detect_tool()
            args: Arguments to pass to the tool
            
        Returns:
            Complete command list ready for subprocess execution
        """
        if tool_info.mode == ExecutionMode.UNAVAILABLE:
            raise RuntimeError(f"Tool {tool_info.name} is not available")
        
        command = tool_info.command_prefix.copy()
        
        if tool_info.mode == ExecutionMode.NATIVE:
            command.append(tool_info.path)
        else:
            command.append(tool_info.name)
        
        command.extend(args)
        
        return command


class ToolConfig(BaseModel):
    """Configuration for tool detection and execution."""
    
    # Execution mode preferences
    execution_mode: Optional[ExecutionMode] = None
    preferred_modes: List[ExecutionMode] = [
        ExecutionMode.NATIVE,
        ExecutionMode.MODULE,
        ExecutionMode.LMOD,
        ExecutionMode.SINGULARITY,
        ExecutionMode.DOCKER
    ]
    
    # Tool-specific settings
    tool_settings: Dict[str, Dict] = {}
    
    # Container settings
    singularity_image_path: Optional[str] = None
    docker_image_prefix: Optional[str] = None
    
    # Module settings
    module_search_paths: List[str] = []
    
    @classmethod
    def from_env(cls) -> "ToolConfig":
        """Create configuration from environment variables."""
        config = cls()
        
        # Check for execution mode override
        if force_mode := os.getenv("BIO_MCP_EXECUTION_MODE"):
            try:
                config.execution_mode = ExecutionMode(force_mode.lower())
            except ValueError:
                logging.warning(f"Invalid execution mode: {force_mode}")
        
        # Check for preferred modes
        if preferred_modes := os.getenv("BIO_MCP_PREFERRED_MODES"):
            try:
                modes = [ExecutionMode(mode.strip().lower()) for mode in preferred_modes.split(",")]
                config.preferred_modes = modes
            except ValueError:
                logging.warning(f"Invalid preferred modes: {preferred_modes}")
        
        # Container settings
        config.singularity_image_path = os.getenv("BIO_MCP_SINGULARITY_PATH")
        config.docker_image_prefix = os.getenv("BIO_MCP_DOCKER_PREFIX")
        
        return config