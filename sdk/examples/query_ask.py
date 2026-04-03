from stixdb_sdk import StixDBClient


def main():
    COLLECTION = "demo_collection"
    
    client = StixDBClient(base_url="http://localhost:4020")
    
    # Ask a synthesis question
    QUESTION = "What is StixDB?"
    print(f"Asking question to collection '{COLLECTION}': {QUESTION}")
    answer = client.query.ask(
        COLLECTION,
        question=QUESTION,
        top_k=10,
        threshold=0.25,
        depth=1,
        system_prompt="Answer the user's question precisely based on the context.",
    )
    print(f"Answer: {answer.get('answer')}")
    client.close()


if __name__ == "__main__":
    main()
