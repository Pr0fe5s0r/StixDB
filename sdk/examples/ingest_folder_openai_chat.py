from openai import OpenAI

from stixdb_sdk import StixDBClient


BASE_URL = "http://localhost:4020"
API_KEY = "my-secret-key"
COLLECTION = "my_pdfs"
PDF_FOLDER = "/path/to/pdf_folder"


def main() -> None:
    stix = StixDBClient(base_url=BASE_URL, api_key=API_KEY)
    result = stix.memory.ingest_folder(
        COLLECTION,
        PDF_FOLDER,
        parser="auto",
        recursive=True,
    )
    print(f"Processed {result['files_processed']} files")
    print(f"Skipped {result['files_skipped']} files")
    stix.close()

    client = OpenAI(
        base_url=f"{BASE_URL}/v1",
        api_key=API_KEY,
    )

    stream = client.chat.completions.create(
        model=COLLECTION,
        messages=[
            {
                "role": "user",
                "content": "What are the main topics covered in these PDFs?",
            }
        ],
        stream=True,
        extra_body={"verbose": True},
    )

    for chunk in stream:
        content = chunk.choices[0].delta.content
        if content:
            print(content, end="", flush=True)
    print()


if __name__ == "__main__":
    main()
