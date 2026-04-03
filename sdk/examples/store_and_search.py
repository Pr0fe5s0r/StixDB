from stixdb_sdk import StixDBClient


def main():
    COLLECTION = "demo_collection"
    
    client = StixDBClient(base_url="http://localhost:4020")
    
    # 1. Store a memory snippet
    print(f"Storing text in '{COLLECTION}'...")
    response = client.memory.store(
        COLLECTION,
        content="StixDB is an agentic context database designed for high precision retrieval.",
        source="manual_entry",
        tags=["stix", "info"],
        node_type="fact",
        importance=0.9,
    )
    print(f"Stored: {response}\n")

    # 2. Search for related information
    QUERY = "How is StixDB designed?"
    print(f"Searching for '{QUERY}'...")
    results = client.search.create(
        QUERY,
        collection=COLLECTION,
        max_results=3,
    )
    print(f"Search results for '{QUERY}':")
    for res in results.get("results", []):
        print(f"- Content: {res.get('content')[:50]}...")
        print(f"  Source: {res.get('source')}")
        print(f"  Score: {res.get('score')}\n")
    client.close()


if __name__ == "__main__":
    main()
