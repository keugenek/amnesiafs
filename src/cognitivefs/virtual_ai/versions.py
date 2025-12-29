"""
Versions handler for /.ai/versions/ (git history browsing)
"""

import json
import time
from typing import Optional, Dict, List
from .base import BaseHandler
from ..utils import format_timestamp


class VersionsHandler(BaseHandler):
    """Handles /.ai/versions/ virtual paths for git history browsing."""

    def getattr(self, target_path: str, parts: List[str]) -> Optional[Dict]:
        """Get attributes for version paths."""
        now = int(time.time())

        # /.ai/versions/ - directory listing
        if not target_path:
            return self._make_dir_stat(now)

        # Reject temp files and editor artifacts
        if target_path.endswith('.tmp') or target_path.startswith('~'):
            return None

        # Check for special files: _help.txt, commits, etc.
        stripped = target_path.strip('/')
        if stripped in ('_help.txt', 'commits', 'log', 'stats'):
            content = self.read(target_path, parts)
            return self._make_file_stat(len(content), now)

        # /.ai/versions/<commit_hash> - commit details
        if len(parts) == 2 and len(parts[1]) >= 7:
            # Looks like a commit hash - check if it's a directory or file
            return self._make_dir_stat(now)

        # /.ai/versions/file/<path> - file version history
        if len(parts) >= 2 and parts[1] == 'file':
            if len(parts) == 2:
                return self._make_dir_stat(now)
            # Return file stat for version history
            content = self._get_file_version_history('/' + '/'.join(parts[2:]))
            return self._make_file_stat(len(content), now)

        # /.ai/versions/<commit_hash>/<path> - file at specific version
        if len(parts) >= 3 and len(parts[1]) >= 7:
            commit_hash = parts[1]
            file_path = '/' + '/'.join(parts[2:])
            content = self._get_file_at_version(file_path, commit_hash)
            if content is not None:
                return self._make_file_stat(len(content), now)

        return self._make_file_stat(4096, now)

    def readdir(self, target_path: str, parts: List[str]) -> List[str]:
        """Read directory for versions paths."""
        if not target_path:
            # Root of versions - show help, commits file, and recent commits
            entries = ['_help.txt', 'commits', 'log', 'stats', 'file']

            # Add recent commit hashes as directories
            vc = self._get_version_control()
            if vc and vc.enabled:
                commits = vc.get_all_commits(limit=10)
                for commit in commits:
                    short_hash = commit['hash'][:8]
                    entries.append(short_hash)

            return entries

        stripped = target_path.strip('/')
        path_parts = stripped.split('/')

        # /.ai/versions/file/ - mirror real filesystem
        if path_parts[0] == 'file':
            if len(path_parts) == 1:
                return self._readdir_mirror('')
            else:
                return self._readdir_mirror('/' + '/'.join(path_parts[1:]))

        # /.ai/versions/<commit_hash>/ - list files changed in commit
        if len(path_parts) == 1 and len(path_parts[0]) >= 7:
            commit_hash = path_parts[0]
            vc = self._get_version_control()
            if vc and vc.enabled:
                files = vc.get_commit_files(commit_hash)
                # Use just the filename for directory listing
                return ['_info.txt', '_diff.txt'] + [f['path'].lstrip('/') for f in files]

        return []

    def read(self, target_path: str, parts: List[str]) -> bytes:
        """Read version control content."""
        if not target_path:
            return self._get_versions_help()

        stripped = target_path.strip('/')

        if stripped == '_help.txt':
            return self._get_versions_help()

        if stripped == 'commits' or stripped == 'log':
            return self._get_commits_list()

        if stripped == 'stats':
            return self._get_version_stats()

        path_parts = stripped.split('/')

        # /.ai/versions/file/<path> - file version history
        if path_parts[0] == 'file' and len(path_parts) > 1:
            file_path = '/' + '/'.join(path_parts[1:])
            return self._get_file_version_history(file_path)

        # /.ai/versions/<commit_hash>/_info.txt - commit info
        if len(path_parts) >= 2 and path_parts[1] == '_info.txt':
            commit_hash = path_parts[0]
            return self._get_commit_info(commit_hash)

        # /.ai/versions/<commit_hash>/_diff.txt - commit diff
        if len(path_parts) >= 2 and path_parts[1] == '_diff.txt':
            commit_hash = path_parts[0]
            return self._get_commit_diff(commit_hash)

        # /.ai/versions/<commit_hash>/<filepath> - file at version
        if len(path_parts) >= 2 and len(path_parts[0]) >= 7:
            commit_hash = path_parts[0]
            file_path = '/' + '/'.join(path_parts[1:])
            content = self._get_file_at_version(file_path, commit_hash)
            if content is not None:
                return content
            return f"File not found at version {commit_hash}: {file_path}\n".encode('utf-8')

        return b""

    def _get_version_control(self):
        """Get version control instance from cognitivefs."""
        if self.cognitivefs and hasattr(self.cognitivefs, 'version_control'):
            return self.cognitivefs.version_control
        return None

    def _readdir_mirror(self, path: str) -> List[str]:
        """Mirror real filesystem directory listing."""
        if self.cognitivefs:
            try:
                return self.cognitivefs.readdir(path, None)
            except:
                return []
        return []

    def _get_versions_help(self) -> bytes:
        """Return help for versions interface."""
        vc = self._get_version_control()
        vc_status = "enabled" if (vc and vc.enabled) else "disabled"

        return f"""# Version Control Interface

## Status: {vc_status}

All files written to CognitiveFS are automatically versioned using git.

## Usage

### View commit history
    cat /.ai/versions/commits         # List recent commits
    cat /.ai/versions/log             # Same as commits
    cat /.ai/versions/stats           # Version control statistics

### Browse commits
    ls /.ai/versions/<commit_hash>/   # List files changed in commit
    cat /.ai/versions/<hash>/_info.txt    # Commit details
    cat /.ai/versions/<hash>/_diff.txt    # Full diff

### View file history
    cat /.ai/versions/file/path/to/file.txt   # Version history for file

### View file at specific version
    cat /.ai/versions/<hash>/path/to/file.txt # File content at version

## Examples

    cat /.ai/versions/commits
    cat /.ai/versions/abc1234/_info.txt
    cat /.ai/versions/file/docs/notes.md

## Notes

- Version control is transparent - no manual commits needed
- Large files (>10MB) use Git LFS if available
- Remote sync available via git commands in the .vcs directory
""".encode('utf-8')

    def _get_commits_list(self) -> bytes:
        """Get list of recent commits."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        commits = vc.get_all_commits(limit=50)

        if not commits:
            return b"No commits yet.\n"

        lines = [
            "# Commit History",
            f"# Total: {len(commits)} commits shown",
            ""
        ]

        for commit in commits:
            ts = format_timestamp(commit['timestamp'], 'full')
            short_hash = commit['hash'][:8]
            message = commit['message'][:60]
            lines.append(f"{short_hash}  {ts}  {message}")

        lines.extend([
            "",
            "---",
            "View commit: cat /.ai/versions/<hash>/_info.txt",
            "View diff: cat /.ai/versions/<hash>/_diff.txt"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_version_stats(self) -> bytes:
        """Get version control statistics."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return json.dumps({'enabled': False}, indent=2).encode('utf-8')

        stats = vc.get_stats()
        return json.dumps(stats, indent=2).encode('utf-8')

    def _get_commit_info(self, commit_hash: str) -> bytes:
        """Get detailed info about a commit."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        # Get commit details
        commits = vc.get_all_commits(limit=100)
        commit_info = None
        for c in commits:
            if c['hash'].startswith(commit_hash):
                commit_info = c
                break

        if not commit_info:
            return f"Commit not found: {commit_hash}\n".encode('utf-8')

        ts = format_timestamp(commit_info['timestamp'], 'full')

        # Get files changed
        files = vc.get_commit_files(commit_info['hash'])

        lines = [
            f"# Commit: {commit_info['hash']}",
            "",
            f"Author:  {commit_info['author']}",
            f"Date:    {ts}",
            f"Message: {commit_info['message']}",
            "",
            f"## Files Changed ({len(files)})",
            ""
        ]

        for f in files:
            status_icon = {'added': '+', 'modified': '~', 'deleted': '-'}.get(f['status'], '?')
            lines.append(f"  {status_icon} {f['path']}")

        lines.extend([
            "",
            f"View diff: cat /.ai/versions/{commit_hash}/_diff.txt"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_commit_diff(self, commit_hash: str) -> bytes:
        """Get diff for a commit."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        diff = vc.get_diff(commit_hash)
        if not diff:
            return f"No diff available for commit: {commit_hash}\n".encode('utf-8')

        return diff.encode('utf-8')

    def _get_file_version_history(self, file_path: str) -> bytes:
        """Get version history for a specific file."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return b"Version control not enabled.\n"

        commits = vc.get_file_history(file_path, limit=30)

        if not commits:
            return f"No version history for: {file_path}\n".encode('utf-8')

        lines = [
            f"# Version History: {file_path}",
            f"# {len(commits)} versions",
            ""
        ]

        for i, commit in enumerate(commits):
            ts = format_timestamp(commit['timestamp'], 'full')
            short_hash = commit['hash'][:8]
            message = commit['message'][:50]
            version_label = "current" if i == 0 else f"v{len(commits) - i}"
            lines.append(f"[{version_label}] {short_hash}  {ts}  {message}")

        lines.extend([
            "",
            "---",
            f"View specific version: cat /.ai/versions/<hash>{file_path}"
        ])

        return "\n".join(lines).encode('utf-8')

    def _get_file_at_version(self, file_path: str, commit_hash: str) -> Optional[bytes]:
        """Get file content at a specific version."""
        vc = self._get_version_control()
        if not vc or not vc.enabled:
            return None

        return vc.get_file_at_version(file_path, commit_hash)
