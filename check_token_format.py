#!/usr/bin/env python3
"""Check what format the token is in the database"""

import asyncio
import aiohttp

async def check_token():
    """Check if the token is hashed in the database"""
    
    # Token from ~/.retunnel.conf
    auth_token = "bSzvRUyPwfLchXDnBvbssldEjDNjkak0nhD8anHSFFA"
    
    print(f"Testing token: {auth_token}")
    print(f"Token length: {len(auth_token)}")
    
    # Try to query the user endpoint
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {auth_token}"}
        
        try:
            async with session.get(
                "http://localhost:6400/api/v1/users/me",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"User data: {data}")
                else:
                    text = await resp.text()
                    print(f"Error: {text}")
        except Exception as e:
            print(f"Request failed: {e}")


if __name__ == "__main__":
    asyncio.run(check_token())