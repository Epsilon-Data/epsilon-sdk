from setuptools import setup, find_packages
import os

here = os.path.dirname(__file__)

# Read version from __version__.py
version_file = os.path.join(here, 'sdk', '__version__.py')
with open(version_file) as f:
    exec(f.read())

# Long description rendered on the PyPI project page (from README.md)
with open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="epsilon-sdk",
    version=__version__,
    description="SDK for accessing remote datasets and archetypes",
    long_description=long_description,
    long_description_content_type='text/markdown',
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