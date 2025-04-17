from fastapi import FastAPI, Query
import google.generativeai as genai
from langdetect import detect
import json
import os
from concurrent.futures import ThreadPoolExecutor

# Configure Gemini API key
genai.configure(api_key="AIzaSyCtbjyQjRa7OmSt1YJDvqKat25f19OiFMk")

app = FastAPI()

# Tidio live chat URL
TIDIO_CHAT_URL = "https://www.tidio.com/panel/inbox/conversations/unassigned/"

# List of URLs to scrape (used only if scraping is required)
WEBSITE_PAGES = [
    "https://dev.tripzoori.com/",
    "https://dev.tripzoori.com/faq-tripzoori"
]

# Scrape website data from multiple pages synchronously (optional)
def scrape_website(urls=WEBSITE_PAGES):
    combined_content = ""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            for url in urls:
                page = browser.new_page()
                page.goto(url)
                page.wait_for_selector("body")
                page_content = page.inner_text("body")
                combined_content += f"\nPage Content from {url}:\n{page_content}\n"
            browser.close()

        # Save the combined content to a JSON file
        with open("website_data.json", "w", encoding="utf-8") as f:
            json.dump({"content": combined_content}, f, indent=4)
        print("Website data successfully scraped and saved to website_data.json.")
        return combined_content
    except Exception as e:
        print(f"Error during scraping: {e}")
        return ""

# Load cached data or use pre-existing file
def load_data():
    try:
        # Check if the file exists
        if os.path.exists("website_data.json"):
            # Try to open and load the file
            with open("website_data.json", "r", encoding="utf-8") as f:
                file_content = f.read().strip()
                if not file_content:  # File is empty
                    print("website_data.json is empty. Please delete the file and restart the application.")
                    return ""
                else:
                    # Attempt to parse the JSON content
                    try:
                        data = json.loads(file_content)
                        print("Successfully loaded website_data.json.")
                        return data.get("content", "")
                    except json.JSONDecodeError:
                        print("Invalid JSON in website_data.json. Please delete the file and restart the application.")
                        return ""
        else:
            # File does not exist, scrape the website (optional)
            print("website_data.json not found. Scraping website...")
            return scrape_website()
    except Exception as e:
        print(f"Unexpected error in load_data: {e}")
        return ""

# Send message to Tidio live chat with error handling
def send_message_to_tidio(message: str):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(TIDIO_CHAT_URL)
            page.wait_for_selector("textarea", timeout=10000)  # Wait for 10 seconds for the textarea to appear
            page.fill("textarea", message)
            page.keyboard.press("Enter")
            browser.close()
    except Exception as e:
        print(f"Error sending message to Tidio: {e}")
        return False
    return True

# Detect if escalation to human is needed
def needs_human_agent(question: str, answer: str) -> bool:
    low_confidence_phrases = [
        "I can't", "I do not", "I am unable", "I don't have information",
        "I cannot", "I am just an AI", "I don't know", "I only provide information",
        "I'm not sure", "I apologize", "Unfortunately, I cannot"
    ]
    trigger_keywords = ["complaints", "refunds", "booking issue", "flight problem", "support", "human agent", "live agent"]
    return any(phrase in answer.lower() for phrase in low_confidence_phrases) or any(keyword in question.lower() for keyword in trigger_keywords)

# Ask question with language awareness
def ask_question(question: str):
    data = load_data()

    try:
        detected_language = detect(question)
    except:
        detected_language = "en"

    # Format the instruction only if it's not English
    language_instruction = f"Respond ONLY in {detected_language}." if detected_language != "en" else "Respond in English."

    prompt = f"""
You are a helpful AI assistant that answers questions based ONLY on the content of the website below.

{language_instruction}

Website Content:
{data}

User's Question: {question}

Answer:
"""

    model = genai.GenerativeModel("gemini-1.5-pro")
    response = model.generate_content(prompt)
    answer = response.text.strip()

    if needs_human_agent(question, answer):
        send_message_to_tidio(f"User asked: '{question}'\nBot could not answer.")
        return {
            "message": "I am unable to answer this question right now, but don't worry, we are connecting you to a live agent. They will assist you shortly.",
            "status": "transferred_to_human"
        }

    return {"question": question, "answer": answer}

# API endpoint
@app.get("/ask")
async def get_answer(question: str = Query(..., title="Question", description="Ask a question about the website")):
    if any(keyword in question.lower() for keyword in ["transfer to human agent", "talk to a person", "speak to support"]):
        message_sent = send_message_to_tidio(f"User requested a human agent for: '{question}'")
        
        # Reassurance message if live agent request is successful
        if message_sent:
            return {
                "message": "Please hold on, we're connecting you to a live agent. You will be assisted shortly.",
                "status": "transferred_to_human"
            }
        else:
            return {
                "message": "Sorry, there was an issue connecting to a live agent. Please try again later.",
                "status": "error"
            }

    # Run synchronous code in a separate thread
    with ThreadPoolExecutor() as executor:
        result = executor.submit(ask_question, question).result()
    return result
