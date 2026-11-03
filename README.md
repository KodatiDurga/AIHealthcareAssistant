# 🏥 AI Healthcare Assistant

## 📌 Project Overview

AI Healthcare Assistant is a healthcare-focused application designed to assist users with healthcare-related information and medical report management.

The project aims to provide an accessible interface for healthcare assistance using modern web technologies and Python.

## 🚀 Features

- AI-powered healthcare assistance
- Healthcare-related question answering
- Medical report upload and management
- Backend API using FastAPI
- Database integration
- User-friendly interface

## 🛠️ Technologies Used

- Python
- FastAPI
- Uvicorn
- HTML, CSS, JavaScript (if applicable)
- SQLite (if applicable)
- Git and GitHub

## 📂 Project Structure

```text
AIHealthcareAssistant/
│
├── main.py
├── requirements.txt
├── .gitignore
├── README.md
├── uploads/
├── templates/
├── static/
└── .venv/
```

*Note: The structure above is an example. Your actual project structure may differ.*

## ⚙️ Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/KodatiDurga/AIHealthcareAssistant.git
```

### 2. Navigate to the project directory

```bash
cd AIHealthcareAssistant
```

### 3. Create a virtual environment

```bash
python -m venv .venv
```

### 4. Activate the virtual environment

**Windows:**

```bash
.venv\Scripts\activate
```

### 5. Install dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the application

For a FastAPI application whose entry point is `main.py` and whose FastAPI instance is named `app`:

```bash
uvicorn main:app --reload
```

Open the following URL in your browser:

```text
http://127.0.0.1:8000
```

FastAPI API documentation:

```text
http://127.0.0.1:8000/docs
```

## 🔐 Security and Privacy

- Do not upload API keys or passwords.
- Keep environment variables in `.env`.
- Do not commit sensitive medical records or patient information.
- Use appropriate authentication and authorization for healthcare data.

## ⚠️ Disclaimer

This application is intended for educational and informational purposes only.

It does not replace professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare professional for medical concerns.

## 👨‍💻 Author

**Kodati Durga**

GitHub: [KodatiDurga](https://github.com/KodatiDurga)

## 📜 License

This project is available for educational purposes.
