import asyncio

from stixdb_sdk import AsyncStixDBClient


async def main():
    client = AsyncStixDBClient()
    
    print("Checking StixDB health asynchronously...")
    health = await client.health()
    print(f"Health: {health}")
    
    COLLECTION = "async_test"
    print(f"\nAsync bulk store in '{COLLECTION}'...")
    items = [
        {"content": "First bit of info", "source": "item1"},
        {"content": "Second bit of info", "source": "item2"},
    ]
    res = await client.memory.bulk_store(COLLECTION, items)
    print(f"Bulk store status: {res}")
    
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
