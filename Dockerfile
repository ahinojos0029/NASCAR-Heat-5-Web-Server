# 1. Use an existing Python image
FROM python:3.11

# 2. Set the working directory inside the container
WORKDIR /

# 3. Copy the requirements file first
COPY requirements.txt .

# 4. Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of the app files
COPY . .

# 6. Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 7. Define the command to run the app
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]