"""Step 0: check that your GOOGLE_API_KEY works.   python scripts/hello_gemini.py"""
import os

from dotenv import load_dotenv
load_dotenv()

from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))
reply = llm.invoke("Say hello to Ravi in one line")
print(reply.content)