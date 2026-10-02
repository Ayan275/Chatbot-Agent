FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    build-essential \
    g++ \
    nlohmann-json3-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

RUN g++ -O3 -std=c++17 -I include -I src src/*.cpp -o chatbot_backend
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 5000
CMD ["gunicorn", "-b", "0.0.0.0:5000", "whatsapp_gemini_agent:app"]
