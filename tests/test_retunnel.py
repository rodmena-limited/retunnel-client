"""
Tests for the ReTunnel package.
"""

from retunnel import start_client


def test_re_tunnel():
    assert start_client() is True, "ReTunnel client did not start successfully"
