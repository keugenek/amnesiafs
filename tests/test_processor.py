"""Unit tests for Processor module - ignore functionality."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from cognitivefs.processor import (
    should_ignore_path,
    IGNORED_DIRECTORIES,
    IGNORED_FILE_PATTERNS,
)


class TestShouldIgnorePath(unittest.TestCase):
    """Test should_ignore_path function."""

    # ==================== .git directory tests ====================

    def test_ignore_git_directory(self):
        """Test .git directory is ignored."""
        self.assertTrue(should_ignore_path('/.git/config'))
        self.assertTrue(should_ignore_path('/.git/objects/pack/pack-123.pack'))
        self.assertTrue(should_ignore_path('/project/.git/HEAD'))

    def test_ignore_git_subdirectories(self):
        """Test .git subdirectories are ignored."""
        self.assertTrue(should_ignore_path('/.git/hooks/pre-commit'))
        self.assertTrue(should_ignore_path('/.git/refs/heads/main'))
        self.assertTrue(should_ignore_path('/.git/logs/HEAD'))

    def test_git_in_filename_not_ignored(self):
        """Test files with 'git' in name but not in .git dir are NOT ignored."""
        self.assertFalse(should_ignore_path('/docs/git-tutorial.md'))
        self.assertFalse(should_ignore_path('/src/git_utils.py'))

    # ==================== Other VCS directories ====================

    def test_ignore_hg_directory(self):
        """Test .hg (Mercurial) directory is ignored."""
        self.assertTrue(should_ignore_path('/.hg/store'))
        self.assertTrue(should_ignore_path('/project/.hg/dirstate'))

    def test_ignore_svn_directory(self):
        """Test .svn (Subversion) directory is ignored."""
        self.assertTrue(should_ignore_path('/.svn/entries'))
        self.assertTrue(should_ignore_path('/project/.svn/wc.db'))

    # ==================== Build/dependency directories ====================

    def test_ignore_node_modules(self):
        """Test node_modules directory is ignored."""
        self.assertTrue(should_ignore_path('/node_modules/lodash/index.js'))
        self.assertTrue(should_ignore_path('/project/node_modules/react/package.json'))

    def test_ignore_pycache(self):
        """Test __pycache__ directory is ignored."""
        self.assertTrue(should_ignore_path('/__pycache__/module.cpython-311.pyc'))
        self.assertTrue(should_ignore_path('/src/__pycache__/utils.cpython-311.pyc'))

    def test_ignore_pytest_cache(self):
        """Test .pytest_cache directory is ignored."""
        self.assertTrue(should_ignore_path('/.pytest_cache/v/cache/lastfailed'))
        self.assertTrue(should_ignore_path('/tests/.pytest_cache/README.md'))

    def test_ignore_venv(self):
        """Test virtual environment directories are ignored."""
        self.assertTrue(should_ignore_path('/.venv/lib/python3.11/site-packages'))
        self.assertTrue(should_ignore_path('/venv/bin/python'))
        self.assertTrue(should_ignore_path('/env/lib/python3.11/site-packages'))

    def test_ignore_build_directories(self):
        """Test build/dist directories are ignored."""
        self.assertTrue(should_ignore_path('/dist/package.tar.gz'))
        self.assertTrue(should_ignore_path('/build/lib/module.py'))

    def test_ignore_ide_directories(self):
        """Test IDE directories are ignored."""
        self.assertTrue(should_ignore_path('/.idea/workspace.xml'))
        self.assertTrue(should_ignore_path('/.vscode/settings.json'))

    # ==================== File pattern tests ====================

    def test_ignore_pyc_files(self):
        """Test .pyc files are ignored."""
        self.assertTrue(should_ignore_path('/module.pyc'))
        self.assertTrue(should_ignore_path('/src/utils.pyc'))

    def test_ignore_log_files(self):
        """Test .log files are ignored."""
        self.assertTrue(should_ignore_path('/app.log'))
        self.assertTrue(should_ignore_path('/logs/error.log'))

    def test_ignore_lock_files(self):
        """Test lock files are ignored."""
        self.assertTrue(should_ignore_path('/poetry.lock'))
        self.assertTrue(should_ignore_path('/package-lock.json'))
        self.assertTrue(should_ignore_path('/yarn.lock'))

    def test_ignore_temp_files(self):
        """Test temp files are ignored."""
        self.assertTrue(should_ignore_path('/file.tmp'))
        self.assertTrue(should_ignore_path('/data.temp'))

    def test_ignore_swap_files(self):
        """Test vim swap files are ignored."""
        self.assertTrue(should_ignore_path('/file.swp'))
        self.assertTrue(should_ignore_path('/file.swo'))

    def test_ignore_backup_files(self):
        """Test backup/autosave files are ignored."""
        self.assertTrue(should_ignore_path('/file.txt~'))
        self.assertTrue(should_ignore_path('/.#file.txt'))
        self.assertTrue(should_ignore_path('/#file.txt#'))

    def test_ignore_compiled_binaries(self):
        """Test compiled binary files are ignored."""
        self.assertTrue(should_ignore_path('/module.so'))
        self.assertTrue(should_ignore_path('/lib.dll'))
        self.assertTrue(should_ignore_path('/app.exe'))
        self.assertTrue(should_ignore_path('/module.o'))
        self.assertTrue(should_ignore_path('/Main.class'))

    # ==================== Files that should NOT be ignored ====================

    def test_normal_source_files_not_ignored(self):
        """Test normal source files are NOT ignored."""
        self.assertFalse(should_ignore_path('/src/main.py'))
        self.assertFalse(should_ignore_path('/src/utils/helper.js'))
        self.assertFalse(should_ignore_path('/lib/module.ts'))

    def test_config_files_not_ignored(self):
        """Test config files are NOT ignored."""
        self.assertFalse(should_ignore_path('/package.json'))
        self.assertFalse(should_ignore_path('/pyproject.toml'))
        self.assertFalse(should_ignore_path('/.gitignore'))
        self.assertFalse(should_ignore_path('/Makefile'))

    def test_documentation_not_ignored(self):
        """Test documentation files are NOT ignored."""
        self.assertFalse(should_ignore_path('/README.md'))
        self.assertFalse(should_ignore_path('/docs/api.md'))
        self.assertFalse(should_ignore_path('/CHANGELOG.txt'))

    def test_data_files_not_ignored(self):
        """Test data files are NOT ignored."""
        self.assertFalse(should_ignore_path('/data/users.json'))
        self.assertFalse(should_ignore_path('/config/settings.yaml'))
        self.assertFalse(should_ignore_path('/data.csv'))

    # ==================== Windows path tests ====================

    def test_windows_paths_normalized(self):
        """Test Windows-style paths are handled correctly."""
        self.assertTrue(should_ignore_path('C:\\project\\.git\\config'))
        self.assertTrue(should_ignore_path('\\project\\node_modules\\lodash'))
        self.assertFalse(should_ignore_path('C:\\project\\src\\main.py'))

    # ==================== Edge cases ====================

    def test_empty_path(self):
        """Test empty path is not ignored."""
        self.assertFalse(should_ignore_path(''))

    def test_root_path(self):
        """Test root path is not ignored."""
        self.assertFalse(should_ignore_path('/'))

    def test_relative_paths(self):
        """Test relative paths work correctly."""
        self.assertTrue(should_ignore_path('.git/config'))
        self.assertTrue(should_ignore_path('node_modules/lodash/index.js'))
        self.assertFalse(should_ignore_path('src/main.py'))


class TestIgnoredDirectoriesSet(unittest.TestCase):
    """Test IGNORED_DIRECTORIES constant."""

    def test_common_vcs_included(self):
        """Test common VCS directories are in the set."""
        self.assertIn('.git', IGNORED_DIRECTORIES)
        self.assertIn('.hg', IGNORED_DIRECTORIES)
        self.assertIn('.svn', IGNORED_DIRECTORIES)

    def test_common_build_dirs_included(self):
        """Test common build directories are in the set."""
        self.assertIn('node_modules', IGNORED_DIRECTORIES)
        self.assertIn('__pycache__', IGNORED_DIRECTORIES)
        self.assertIn('dist', IGNORED_DIRECTORIES)
        self.assertIn('build', IGNORED_DIRECTORIES)

    def test_common_venv_dirs_included(self):
        """Test virtual environment directories are in the set."""
        self.assertIn('.venv', IGNORED_DIRECTORIES)
        self.assertIn('venv', IGNORED_DIRECTORIES)
        self.assertIn('env', IGNORED_DIRECTORIES)


class TestIgnoredFilePatternsSet(unittest.TestCase):
    """Test IGNORED_FILE_PATTERNS constant."""

    def test_compiled_patterns_included(self):
        """Test compiled file patterns are in the set."""
        patterns_str = ''.join(IGNORED_FILE_PATTERNS)
        self.assertIn('pyc', patterns_str)
        self.assertIn('class', patterns_str)

    def test_temp_patterns_included(self):
        """Test temp file patterns are in the set."""
        patterns_str = ''.join(IGNORED_FILE_PATTERNS)
        self.assertIn('tmp', patterns_str)
        self.assertIn('swp', patterns_str)


if __name__ == '__main__':
    unittest.main()
