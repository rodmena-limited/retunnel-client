#!/usr/bin/env python
"""
Demo of the retunnel client
"""

import asyncio
import logging
from retunnel import HighPerformanceClient, TunnelConfig

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    # Configuration
    server_addr = "localhost:6400"
    local_port = 5003
    
    logger.info(f"Starting ReTunnel client demo...")
    logger.info(f"Server: {server_addr}")
    logger.info(f"Local port: {local_port}")
    
    # Create client
    client = HighPerformanceClient(server_addr)
    
    try:
        # Connect to server
        logger.info("Connecting to ReTunnel server...")
        await client.connect()
        logger.info(f"Connected! Client ID: {client.client_id}")
        
        # Request tunnel
        config = TunnelConfig(protocol="http", local_port=local_port)
        tunnel = await client.request_tunnel(config)
        
        logger.info("\n" + "=" * 60)
        logger.info("TUNNEL ESTABLISHED!")
        logger.info(f"Tunnel URL: {tunnel.url}")
        logger.info(f"Tunnel ID: {tunnel.id}")
        logger.info("=" * 60)
        
        logger.info("\nPress Ctrl+C to stop the tunnel...")
        
        # Keep running
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        logger.info("\nShutting down tunnel...")
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.close()
        logger.info("Tunnel closed")

if __name__ == "__main__":
    asyncio.run(main())