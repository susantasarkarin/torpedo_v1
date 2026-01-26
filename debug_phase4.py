#!/usr/bin/env python
import httpx
import json
import asyncio

async def test():
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post('http://139.59.32.72:8000/agents/run/4', json={'phase': 4})
        data = response.json()
        print(json.dumps(data, indent=2))

asyncio.run(test())
