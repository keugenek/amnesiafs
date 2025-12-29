"""
Git-based version control integration for CognitiveFS.

Stores filesystem snapshots in a git repository inside the mounted volume
at /.vcs/. Uses git LFS for large files when available.

Supports syncing to external remotes (GitHub, GitLab, etc.) via config.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Iterable, Optional, Dict, Any


class GitVersionControl:
    """Manage a git repository for filesystem versioning."""

    DEFAULT_LFS_THRESHOLD_BYTES = 10 * 1024 * 1024

    # Paths to exclude from version control (prevent infinite loops)
    EXCLUDED_PREFIXES = ('.ai/', '.vcs/', '.vcs\\')

    def __init__(
        self,
        repo_path: str,
        logger,
        lfs_threshold_bytes: int = DEFAULT_LFS_THRESHOLD_BYTES,
        remote_config: Dict[str, Any] = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.logger = logger
        self.lfs_threshold_bytes = lfs_threshold_bytes
        self.enabled = False
        self.lfs_available = False
        self.remote_config = remote_config or {}

    def init_repo(self) -> None:
        """Initialize the git repository if possible."""
        if not self._git_available():
            self.logger("Git not available; version control disabled")
            return

        self.repo_path.mkdir(parents=True, exist_ok=True)
        if not (self.repo_path / ".git").exists():
            self._run_git(["init"])
            self._run_git(["config", "user.name", "CognitiveFS"])
            self._run_git(["config", "user.email", "cognitivefs@local"])

        self.lfs_available = self._git_lfs_available()
        if self.lfs_available:
            self._run_git(["lfs", "install", "--local"])

        self.enabled = True

    def has_commits(self) -> bool:
        """Return True if the repo has any commits."""
        result = self._run_git(["rev-parse", "--verify", "HEAD"], check=False)
        return result.returncode == 0

    def record_file(self, path: str, data: bytes, commit: bool = True) -> None:
        """Record a file snapshot in the repo."""
        rel_path = self._relative_path(path)
        if rel_path is None:
            return

        full_path = self.repo_path / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)

        if self.lfs_available and len(data) >= self.lfs_threshold_bytes:
            self._track_lfs(rel_path)

        self._run_git(["add", rel_path])
        if commit:
            self.commit_pending(f"Update {path}")

    def record_directory(self, path: str, commit: bool = True) -> None:
        """Record a directory creation in the repo."""
        rel_path = self._relative_path(path)
        if rel_path is None:
            return

        dir_path = self.repo_path / rel_path
        dir_path.mkdir(parents=True, exist_ok=True)
        placeholder = dir_path / ".gitkeep"
        if not placeholder.exists():
            placeholder.write_bytes(b"")
        self._run_git(["add", str(placeholder.relative_to(self.repo_path))])
        if commit:
            self.commit_pending(f"Add directory {path}")

    def remove_path(self, path: str, commit: bool = True) -> None:
        """Record removal of a file or directory."""
        rel_path = self._relative_path(path)
        if rel_path is None:
            return
        self._run_git(["rm", "-r", "--ignore-unmatch", rel_path], check=False)
        if commit:
            self.commit_pending(f"Remove {path}")

    def rename_path(self, old: str, new: str, commit: bool = True) -> None:
        """Record rename or move of a path."""
        old_rel = self._relative_path(old)
        new_rel = self._relative_path(new)
        if old_rel is None or new_rel is None:
            return

        old_full = self.repo_path / old_rel
        new_full = self.repo_path / new_rel
        if not old_full.exists():
            return

        new_full.parent.mkdir(parents=True, exist_ok=True)
        result = self._run_git(["mv", "-f", old_rel, new_rel], check=False)
        if result.returncode != 0:
            old_full.rename(new_full)
            self._run_git(["add", new_rel])
            self._run_git(["rm", "-r", "--ignore-unmatch", old_rel], check=False)

        if commit:
            self.commit_pending(f"Rename {old} -> {new}")

    def commit_pending(self, message: str) -> None:
        """Commit staged changes if there are any."""
        status = self._run_git(["status", "--porcelain"], check=False)
        if status.returncode != 0:
            return
        if not status.stdout.strip():
            return
        self._run_git(["commit", "-m", message], check=False)

    def _track_lfs(self, rel_path: str) -> None:
        """Track a file with git LFS."""
        self._run_git(["lfs", "track", rel_path], check=False)
        attributes_path = self.repo_path / ".gitattributes"
        if attributes_path.exists():
            self._run_git(["add", ".gitattributes"], check=False)

    def _relative_path(self, path: str) -> Optional[str]:
        """Convert a filesystem path to a safe repo-relative path.

        Returns None for excluded paths (.ai/, .vcs/) to prevent infinite loops.
        """
        cleaned = path.replace("\\", "/")
        cleaned = cleaned.lstrip("/")

        # Check against excluded prefixes
        if not cleaned:
            return None
        for prefix in self.EXCLUDED_PREFIXES:
            if cleaned.startswith(prefix) or cleaned == prefix.rstrip('/'):
                return None

        parts = [part for part in cleaned.split("/") if part and part != "."]
        if any(part == ".." for part in parts):
            return None
        return "/".join(parts)

    # ========== Remote Sync Methods ==========

    def add_remote(self, name: str, url: str) -> bool:
        """Add a git remote for syncing."""
        result = self._run_git(["remote", "add", name, url], check=False)
        if result.returncode == 0:
            self.logger(f"Added remote '{name}': {url}")
            return True
        # Remote might already exist, try to update it
        result = self._run_git(["remote", "set-url", name, url], check=False)
        return result.returncode == 0

    def remove_remote(self, name: str) -> bool:
        """Remove a git remote."""
        result = self._run_git(["remote", "remove", name], check=False)
        return result.returncode == 0

    def list_remotes(self) -> Dict[str, str]:
        """List all configured remotes."""
        result = self._run_git(["remote", "-v"], check=False)
        remotes = {}
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if line and '(fetch)' in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        remotes[parts[0]] = parts[1]
        return remotes

    def push(self, remote: str = "origin", branch: str = "master", force: bool = False) -> bool:
        """Push to remote repository."""
        args = ["push", remote, branch]
        if force:
            args.insert(1, "--force")
        result = self._run_git(args, check=False)
        if result.returncode == 0:
            self.logger(f"Pushed to {remote}/{branch}")
            return True
        self.logger(f"Push failed: {result.stderr}")
        return False

    def pull(self, remote: str = "origin", branch: str = "master") -> bool:
        """Pull from remote repository."""
        result = self._run_git(["pull", remote, branch], check=False)
        if result.returncode == 0:
            self.logger(f"Pulled from {remote}/{branch}")
            return True
        self.logger(f"Pull failed: {result.stderr}")
        return False

    def sync_to_remote(self, remote: str = "origin") -> bool:
        """Sync local changes to remote (commit pending + push)."""
        self.commit_pending("Auto-sync")
        return self.push(remote)

    def setup_remote_from_config(self) -> bool:
        """Setup remote from config if provided."""
        if not self.remote_config:
            return False

        url = self.remote_config.get('url')
        name = self.remote_config.get('name', 'origin')

        if url:
            return self.add_remote(name, url)
        return False

    def _git_available(self) -> bool:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0

    def _git_lfs_available(self) -> bool:
        return subprocess.run(["git", "lfs", "version"], capture_output=True).returncode == 0

    def _run_git(self, args: Iterable[str], check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.logger(f"Git command failed: git {' '.join(args)}\n{result.stderr}")
        return result
