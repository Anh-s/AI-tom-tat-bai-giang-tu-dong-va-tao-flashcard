import os
import json
import requests
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from docx import Document
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import re


GEMINI_API_KEY = "AIzaSyCqZwHYHK8Hltz4hCtWqe4gts59iygLLck"
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={GEMINI_API_KEY}"


app = Flask(__name__)
CORS(app)


last_uploaded_text = ""
last_summary = ""
last_flashcards = []


def convert_pdf_to_images(file_path):
    images = []
    try:
        doc = fitz.open(file_path)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=300)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        doc.close()
    except Exception as e:
        print(f"Lỗi PDF->Ảnh: {e}")
    return images

def read_text_from_file(file_path):
    _, file_extension = os.path.splitext(file_path)
    text = ""
    file_extension = file_extension.lower()
    try:
        if file_extension == '.txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        elif file_extension == '.docx':
            doc = Document(file_path)
            for para in doc.paragraphs:
                text += para.text + '\n'
        elif file_extension == '.pdf':
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text()
            doc.close()
            if not text.strip(): 
                images = convert_pdf_to_images(file_path)
                ocr_text = ""
                for img in images:
                    ocr_text += pytesseract.image_to_string(img, lang='vie')
                text = ocr_text
        else:
            return "Định dạng tệp không được hỗ trợ."
        return text
    except Exception as e:
        return f"Lỗi khi đọc tệp: {e}"


def process_text_with_llm(text, prompt):
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": f"{prompt}\n\n{text}"}]}
        ]
    }
    try:
        response = requests.post(
            GEMINI_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload)
        )
        response.raise_for_status()
        result = response.json()
        if result and "candidates" in result and len(result["candidates"]) > 0:
            return result["candidates"][0]["content"]["parts"][0]["text"].strip()
        else:
            return "Không nhận được phản hồi hợp lệ từ Gemini."
    except requests.exceptions.RequestException as e:
        return f"Lỗi API: {e}"

def summarize_lecture(text):
    prompt = "Tóm tắt bài giảng sau đây ngắn gọn, súc tích và đầy đủ ý chính:"
    return process_text_with_llm(text, prompt)

def create_flashcards(text, count=5):
    prompt = f"""Dựa trên nội dung sau, hãy tạo đúng {count} flashcards.
Mỗi flashcard ở dạng:
Q: [Câu hỏi]
A: [Câu trả lời]"""
    raw = process_text_with_llm(text, prompt)
    flashcards = []
    lines = raw.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].startswith("Q:") and lines[i+1].startswith("A:"):
            q = lines[i].replace("Q:", "").strip()
            a = lines[i+1].replace("A:", "").strip()
            if q and a:
                flashcards.append({"question": q, "answer": a})
    return flashcards


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload_file():
    global last_uploaded_text, last_summary, last_flashcards

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "Không có file"}), 400

    filepath = os.path.join("uploads", file.filename)
    os.makedirs("uploads", exist_ok=True)
    file.save(filepath)

    text = read_text_from_file(filepath)
    if text.startswith("Lỗi") or text.startswith("Định dạng"):
        return jsonify({"error": text}), 400

    last_uploaded_text = text
    last_summary = summarize_lecture(text)
    last_flashcards = create_flashcards(text, count=5)

    return jsonify({"summary": last_summary, "flashcards": last_flashcards})

@app.route("/flashcards", methods=["POST"])
def flashcards():
    global last_uploaded_text, last_flashcards
    if not last_uploaded_text:
        return jsonify({"error": "Chưa có nội dung nào để tạo flashcards"}), 400

    data = request.get_json()
    count = data.get("count", 5)
    try:
        count = int(count)
    except:
        count = 5

    new_flashcards = create_flashcards(last_uploaded_text, count)
    last_flashcards.extend(new_flashcards)
    return jsonify({"flashcards": new_flashcards})

@app.route("/ask", methods=["POST"])
def ask():
    global last_uploaded_text, last_flashcards
    data = request.get_json()
    question = data.get("question", "")
    context = data.get("context", last_uploaded_text)
    if not question:
        return jsonify({"error": "Chưa nhập câu hỏi"}), 400

    match = re.search(r"tạo thêm\s+(\d+)\s+flashcard", question.lower())
    if match:
        count = int(match.group(1))
        new_flashcards = create_flashcards(last_uploaded_text, count)
        last_flashcards.extend(new_flashcards)
        return jsonify({"flashcards": new_flashcards})

    prompt = f"Dựa trên nội dung sau, hãy trả lời câu hỏi: {question}"
    answer = process_text_with_llm(context, prompt)
    return jsonify({"answer": answer})

@app.route("/download", methods=["GET"])
def download():
    global last_summary, last_flashcards
    filepath = "result.txt"
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=== Tóm tắt ===\n")
        f.write(last_summary + "\n\n")
        f.write("=== Flashcards ===\n")
        for idx, fc in enumerate(last_flashcards, 1):
            f.write(f"{idx}. Q: {fc['question']}\n   A: {fc['answer']}\n")
    return send_file(filepath, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
