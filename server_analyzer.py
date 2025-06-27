# server_analyzer.py - Simple and generic YAML analyzer

import yaml
import os
from typing import List, Dict, Any


class DatasetAnalyzer:
    """
    Simple analyzer that reads YAML manifest and extracts dataset requirements
    Nothing else - just tells you which datasets you need to fetch
    """

    def __init__(self, yaml_file: str):
        self.yaml_file = yaml_file
        self.manifest = None

    def analyze(self) -> Dict[str, Any]:
        """
        Analyze YAML file and return dataset requirements
        Returns: List of datasets that need to be fetched
        """

        if not os.path.exists(self.yaml_file):
            raise FileNotFoundError(f"YAML file not found: {self.yaml_file}")

        # Load YAML
        with open(self.yaml_file, 'r') as f:
            self.manifest = yaml.safe_load(f)

        # Extract dataset requirements
        datasets_needed = []

        for dataset_info in self.manifest.get('datasets', []):
            datasets_needed.append(dataset_info['dataset_id'])

        return {
            'analysis_name': self.manifest.get('analysis', {}).get('name', 'Unknown'),
            'script_file': self.manifest.get('analysis', {}).get('script_file', 'Unknown'),
            'datasets_needed': datasets_needed
        }


def analyze_yaml(yaml_file: str) -> Dict[str, Any]:
    """
    Simple function to analyze YAML and get dataset requirements

    Args:
        yaml_file: Path to YAML manifest file

    Returns:
        Dict with dataset requirements
    """
    analyzer = DatasetAnalyzer(yaml_file)
    return analyzer.analyze()


# Example usage
if __name__ == "__main__":

    # Analyze a YAML manifest
    try:
        result = analyze_yaml("build/example.yml")

        print("    Analysis Results:")
        print(f"   Name: {result['analysis_name']}")
        print(f"   Script: {result['script_file']}")
        print(f"   Datasets needed: {result['datasets_needed']}")

        print(f"\nServer needs to fetch these datasets:")
        for dataset_id in result['datasets_needed']:
            print(f"   - {dataset_id}")

    except FileNotFoundError:
        print("YAML file not found")
    except Exception as e:
        print(f"Analysis failed: {e}")