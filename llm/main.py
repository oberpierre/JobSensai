#!/usr/bin/env python3
"""
JobSensai LLM Module
A smart LLM-powered job board assistant
"""

import logging

from model import LLMModel

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    llm_model = LLMModel()
    
    while True:
        try:
            prompt = input("Enter your prompt (or 'exit' to quit): ")
            if prompt.lower() == 'exit':
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
