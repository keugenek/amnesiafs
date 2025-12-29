"""
Git Sync Module for CognitiveFS (Temporary Solution).

Syncs the external VCS repo (which mirrors volume content) to a remote git repository.
Config is read from /.cognitivefs.yaml on the mounted volume.

NOTE: This is a temporary solution. Git cannot operate directly on FUSE volumes.
Future plan: Replace with file-level delta sync to cloud storage.

Config file format:
```yaml
sync:
  enabled: true
  remote_name: origin
  branch: master
  interval_seconds: 300
  auto_commit: true
  commit_message: "Auto-sync from CognitiveFS"
```
"""

import os
import subprocess
import time
import threading
import yaml
from typing import Optional, Dict, Any, Callable
from pathlib import Path


CONFIG_FILENAME = ".cognitivefs.yaml"

DEFAULT_CONFIG = {
    'sync': {
        'enabled': False,
        'remote_name': 'origin',
        'branch': 'master',
        'interval_seconds': 300,
        'auto_commit': True,
        'commit_message': 'Auto-sync from CognitiveFS',
    }
}


class SyncManager:
    """Manages automatic git sync using external VCS repo."""

    def __init__(
        self,
        vcs_repo_path: str,
        config_reader: Callable[[], Optional[bytes]],
        logger: Callable[[str], None],
    ):
        """
        Initialize sync manager.

        Args:
            vcs_repo_path: Path to the external VCS repo (e.g., "C:/Users/admin/test.vcs")
            config_reader: Function to read config file bytes from filesystem
            logger: Logging function
        """
        self.vcs_repo_path = str(vcs_repo_path)
        self.config_reader = config_reader
        self.logger = logger

        self._config: Dict[str, Any] = {}
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the sync manager background thread."""
        self._stop_event.clear()
        self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._sync_thread.start()
        self.logger("Sync manager started")

    def stop(self):
        """Stop the sync manager."""
        self._stop_event.set()
        if self._sync_thread:
            self._sync_thread.join(timeout=5)
        self.logger("Sync manager stopped")

    def _run_git(self, args: list) -> subprocess.CompletedProcess:
        """Run a git command in the VCS repo directory."""
        result = subprocess.run(
            ["git"] + args,
            cwd=self.vcs_repo_path,
            capture_output=True,
            text=True,
        )
        return result

    def _sync_loop(self):
        """Main sync loop - runs in background thread."""
        last_sync_time = 0

        while not self._stop_event.is_set():
            try:
                self._load_config()

                sync_config = self._config.get('sync', {})

                if not sync_config.get('enabled', False):
                    self._stop_event.wait(30)
                    continue

                interval = sync_config.get('interval_seconds', 300)
                current_time = time.time()

                if current_time - last_sync_time >= interval:
                    self._do_sync()
                    last_sync_time = current_time

                self._stop_event.wait(min(30, interval))

            except Exception as e:
                self.logger(f"Sync error: {e}")
                self._stop_event.wait(60)

    def _load_config(self):
        """Load config from filesystem."""
        try:
            data = self.config_reader()
            if data:
                self._config = yaml.safe_load(data.decode('utf-8', errors='replace')) or {}
            else:
                self._config = {}
        except Exception as e:
            self.logger(f"Failed to load sync config: {e}")
            self._config = {}

    def _do_sync(self):
        """Perform a sync operation."""
        if not os.path.isdir(os.path.join(self.vcs_repo_path, '.git')):
            self.logger("No git repo in VCS path - sync skipped")
            return

        sync_config = self._config.get('sync', {})
        remote_name = sync_config.get('remote_name', 'origin')
        branch = sync_config.get('branch', 'master')
        auto_commit = sync_config.get('auto_commit', True)
        commit_message = sync_config.get('commit_message', 'Auto-sync from CognitiveFS')

        # Auto-commit if enabled
        if auto_commit:
            self._run_git(["add", "-A"])
            status = self._run_git(["status", "--porcelain"])
            if status.stdout.strip():
                result = self._run_git(["commit", "-m", commit_message])
                if result.returncode == 0:
                    self.logger("Committed pending changes")

        # Push to remote
        self.logger(f"Syncing to {remote_name}/{branch}...")
        result = self._run_git(["push", remote_name, branch])

        if result.returncode == 0:
            self.logger(f"Sync complete to {remote_name}/{branch}")
        else:
            self.logger(f"Sync failed: {result.stderr.strip()}")

    def trigger_sync(self):
        """Manually trigger a sync operation."""
        self._load_config()
        self._do_sync()

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        self._load_config()
        sync_config = self._config.get('sync', {})

        remotes = {}
        if os.path.isdir(os.path.join(self.vcs_repo_path, '.git')):
            result = self._run_git(["remote", "-v"])
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line and '(fetch)' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            remotes[parts[0]] = parts[1]

        return {
            'enabled': sync_config.get('enabled', False),
            'remote_name': sync_config.get('remote_name', 'origin'),
            'branch': sync_config.get('branch', 'master'),
            'interval_seconds': sync_config.get('interval_seconds', 300),
            'vcs_repo_path': self.vcs_repo_path,
            'remotes': remotes,
        }


def generate_default_config_content() -> bytes:
    """Generate default config file content."""
    header = """# CognitiveFS Sync Configuration
# Edit this file to configure automatic git sync

"""
    config_yaml = yaml.dump(DEFAULT_CONFIG, default_flow_style=False, sort_keys=False)
    return (header + config_yaml).encode('utf-8')
