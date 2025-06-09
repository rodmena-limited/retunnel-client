#!/usr/bin/env python
"""Test the retunnel CLI client"""

import subprocess
import time
import sys

def test_retunnel_cli():
    print("Testing retunnel CLI...")
    
    # Start the retunnel client
    process = subprocess.Popen(
        ["uv", "run", "retunnel", "http", "5003", "--server", "localhost:6400"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        universal_newlines=True
    )
    
    # Read output for 5 seconds
    start_time = time.time()
    tunnel_url = None
    
    while time.time() - start_time < 5:
        line = process.stdout.readline()
        if line:
            print(line.strip())
            # Look for tunnel URL
            if "http://localhost:" in line or "Tunnel Active" in line:
                tunnel_url = line.strip()
        
        # Check if process exited
        if process.poll() is not None:
            print(f"Process exited with code: {process.returncode}")
            break
    
    # Clean up
    process.terminate()
    process.wait()
    
    print("\nTest completed!")
    if tunnel_url:
        print(f"Successfully established tunnel!")
    else:
        print("Failed to establish tunnel")

if __name__ == "__main__":
    test_retunnel_cli()