from stixdb_sdk import StixDBClient


def main():
    # Initialize the client (defaults to http://localhost:4020)
    client = StixDBClient(base_url="http://localhost:4020")
    
    print("Checking StixDB Engine health...")
    try:
        health = client.health()
        print(f"Health check: {health}")
    except Exception as e:
        print(f"Failed to connect to StixDB: {e}")


if __name__ == "__main__":
    main()
