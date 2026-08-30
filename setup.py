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
    # The chat's custom elements ship with the package and are copied into
    # the project's public/ at start-up.
    package_data={'sdk': ['elements/*.jsx']},
    include_package_data=True,
    install_requires=[
        'requests',
        'typer[all]',
        'pyyaml'
    ],
    extras_require={
        'dev': ['bump-my-version'],
        # Optional. Without it the copilot reads its API key from the
        # environment instead; nothing else changes.
        'copilot': ['keyring>=23.0'],
        # The chat UI. Heavy -- pulls FastAPI, uvicorn and ~140 packages --
        # so it stays out of the default install.
        'chat': ['chainlit>=2.12', 'SQLAlchemy>=2.0', 'aiosqlite>=0.19',
                 'greenlet>=3.0'],
    },
    entry_points={
        'console_scripts': [
            'epsilon=sdk.epsilon_cli:app',
        ],
    },
    python_requires='>=3.7',
)