from setuptools import setup, find_packages
import os

# Read version from __version__.py
version_file = os.path.join(os.path.dirname(__file__), 'sdk', '__version__.py')
with open(version_file) as f:
    exec(f.read())

setup(
    name="epsilon-sdk",
    version=__version__,
    description="SDK for accessing remote datasets and archetypes",
    packages=find_packages(),
    install_requires=[
        'requests',
        'typer[all]',
        'pyyaml'
    ],
    extras_require={
        'dev': ['bump-my-version']
    },
    entry_points={
        'console_scripts': [
            'epsilon=sdk.epsilon_cli:app',
        ],
    },
    python_requires='>=3.7',
)