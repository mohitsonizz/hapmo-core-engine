# 1. Use an official, lightweight Python operating system
FROM python:3.10-slim

# 2. Set our working folder inside the container
WORKDIR /app

# 3. Copy our requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. THE MAGIC: Install Chromium AND all missing Linux system drivers
RUN playwright install chromium
RUN playwright install-deps

# 5. Copy the rest of our code
COPY . .

# 6. Open the port and start the Hapmo API
EXPOSE 10000
CMD ["uvicorn", "hapmo_api:app", "--host", "0.0.0.0", "--port", "10000"]
