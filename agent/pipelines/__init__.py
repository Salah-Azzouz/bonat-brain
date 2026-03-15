"""
Bonat Agent Pipelines

This module contains the pipeline implementations that are exposed as tools.
Each pipeline encapsulates complex multi-step workflows.
"""

from .data_pipeline import execute_data_pipeline

__all__ = ["execute_data_pipeline"]
