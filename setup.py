from setuptools import setup, find_packages

setup(
    name="epsilon-sdk",
    version="0.1.0",
    description="SDK for accessing remote datasets and archetypes",
    packages=find_packages(),
    install_requires=[
        'requests',
        'typer[all]'
    ],
    entry_points={
        'console_scripts': [
            'epsilon=sdk.epsilon_cli:app',
        ],
    },
    python_requires='>=3.7',
)