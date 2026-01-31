#!/usr/bin/env python3
"""
JobSensai LLM Module
A smart LLM-powered job board assistant
"""

import logging
import os

from dotenv import load_dotenv
from model import LLMModel

load_dotenv()
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
    OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
    OLLAMA_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
    llm_model = LLMModel(base_url=OLLAMA_BASE_URL)

    while True:
        try:
            prompt = input("Enter your prompt (or 'exit' to quit): ")
            if prompt.lower() == "exit":
                print("Exiting...")
                break

            response = llm_model.generate_response(prompt)
            print("LLM Response:", response)

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            logger.error(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
