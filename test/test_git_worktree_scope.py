"""Tests for :mod:`kiro_crew.git_worktree_scope`.

The shared classification all four filter-driver guards consult AFTER a
``--worktree`` config probe fails — never to gate whether the probe runs.
Only a genuinely ABSENT ``config.worktree`` reads as the empty scope git
creates the file lazily for; every present entry — regular or not — and every
other stat outcome fails closed, keeping the caller's refusal.
"""

from __future__ import annotations

import os

import pytest

from kiro_crew.git_worktree_scope import worktree_probe_failure_is_empty_scope


def _gitdir(tmp_path):
    d = tmp_path / "repo" / ".git"
    d.mkdir(parents=True)
    return d


def test_absent_file_is_the_empty_scope(tmp_path):
    d = _gitdir(tmp_path)
    assert worktree_probe_failure_is_empty_scope(str(d), str(tmp_path)) is True


def test_trailing_newline_is_gits_terminator_not_the_path(tmp_path):
    """Raw ``rev-parse`` stdout ends in one newline; the classifier removes
    exactly that terminator and inspects the real path."""
    d = _gitdir(tmp_path)
    (d / "config.worktree").write_text("garbage [[[ not config\n")
    assert worktree_probe_failure_is_empty_scope(f"{d}\n", str(tmp_path)) is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX path semantics")
def test_cr_before_the_newline_is_path_content_on_posix(tmp_path):
    """On POSIX git terminates with a bare LF, so a CR ahead of it belongs to
    the real directory name; removing it would lstat a different path and
    wrongly clear a scope whose config file exists."""
    d = tmp_path / "repo" / ".git\r"
    d.mkdir(parents=True)
    (d / "config.worktree").write_text("garbage [[[ not config\n")
    assert worktree_probe_failure_is_empty_scope(f"{d}\n", str(tmp_path)) is False


@pytest.mark.skipif(os.name == "nt", reason="trailing-space dirs are POSIX-only")
def test_whitespace_bearing_git_dir_is_not_rewritten(tmp_path):
    """A git dir whose real name ends in a space must be lstat'ed AS IS: a
    ``.strip()`` would inspect a different, nonexistent path and clear a
    scope whose config file exists."""
    d = tmp_path / "repo" / ".git "
    d.mkdir(parents=True)
    (d / "config.worktree").write_text("garbage [[[ not config\n")
    assert worktree_probe_failure_is_empty_scope(f"{d}\n", str(tmp_path)) is False


def test_present_file_keeps_the_refusal(tmp_path):
    """A probe that failed while the file EXISTS is a garbled/unreadable scope,
    never the empty one — the guard must keep refusing."""
    d = _gitdir(tmp_path)
    (d / "config.worktree").write_text("garbage [[[ not config\n")
    assert worktree_probe_failure_is_empty_scope(str(d), str(tmp_path)) is False


def test_relative_gitdir_joins_onto_base(tmp_path):
    d = _gitdir(tmp_path)
    (d / "config.worktree").write_text("")
    rel = os.path.join("repo", ".git")
    assert worktree_probe_failure_is_empty_scope(rel, str(tmp_path)) is False


def test_empty_gitdir_fails_closed(tmp_path):
    """An unlocatable git dir cannot confirm absence, so the failure is not
    classified as the empty scope and the caller's refusal stands."""
    assert worktree_probe_failure_is_empty_scope("", str(tmp_path)) is False


@pytest.mark.skipif(os.name == "nt", reason="mkfifo is POSIX-only")
def test_fifo_keeps_the_refusal(tmp_path):
    """A present-but-non-regular entry must NOT read as the empty scope: git
    still loads the path, so clearing the failure would skip the refusal on
    exactly the entry an evader would plant. ``os.path.isfile`` answers False
    for a FIFO; the lstat-based check fails closed."""
    d = _gitdir(tmp_path)
    os.mkfifo(d / "config.worktree")
    assert worktree_probe_failure_is_empty_scope(str(d), str(tmp_path)) is False


def test_broken_symlink_keeps_the_refusal(tmp_path):
    d = _gitdir(tmp_path)
    try:
        (d / "config.worktree").symlink_to(d / "nowhere")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert worktree_probe_failure_is_empty_scope(str(d), str(tmp_path)) is False
