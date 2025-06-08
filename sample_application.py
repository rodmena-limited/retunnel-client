#!/usr/bin/env python3
"""
ReTunnel Sample Application

This is a simple example demonstrating how to use the ReTunnel package.
"""

from retunnel import ReTunnelClient, hello


def main():
    # Simple hello message
    print(hello())
    print()

    # Example 1: Basic usage
    print("Example 1: Basic usage")
    print("-" * 40)
    client = ReTunnelClient()

    if client.connect():
        print("Connected to ReTunnel service")
        tunnel_url = client.create_tunnel(port=8080)
        print(f"Tunnel created: {tunnel_url}")
        client.close()
        print("Connection closed")

    print()

    # Example 2: Using context manager
    print("Example 2: Using context manager")
    print("-" * 40)
    with ReTunnelClient(api_key="placeholder-api-key") as client:
        print("Connected via context manager")
        tunnel_url = client.create_tunnel(port=3000)
        print(f"Tunnel created: {tunnel_url}")
    print("Context manager automatically closed connection")

    print()
    print("Visit https://retunnel.com to learn more about ReTunnel!")


if __name__ == "__main__":
    main()
