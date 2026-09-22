from setuptools import setup, find_namespace_packages
import os

# Read version from __version__.py
version_file = os.path.join(os.path.dirname(__file__), 'sdk', '__version__.py')
with open(version_file) as f:
    exec(f.read())

setup(
    name="epsilon-sdk",
    version=__version__,
    description="SDK for accessing remote datasets and archetypes",
    packages=find_namespace_packages(include=['sdk', 'sdk.*'], exclude=['*.__pycache__']),
    # The workspace's browser files and the notebook runtime image definition.
    package_data={'sdk': ['static/workbench/*',
                          'workbench/runtime/Dockerfile', 'workbench/runtime/worker.py', 'workbench/runtime/requirements.txt']},
    include_package_data=True,
    install_requires=[
        'requests',
        'typer[all]',
        'pyyaml',
        'PyJWT[crypto]>=2.10,<3'
    ],
    extras_require={
        'dev': ['bump-my-version'],
        'workbench': ['fastapi>=0.115,<1', 'uvicorn>=0.30,<1', 'pydantic>=2.7,<3', 'markdown-it-py>=3,<5'],
        # Optional. Without it the copilot reads its API key from the
        # environment instead; nothing else changes.
        'copilot': ['keyring>=23.0']
    },
    entry_points={
        'console_scripts': [
            'epsilon=sdk.epsilon_cli:app',
        ],
    },
    python_requires='>=3.9',
)
