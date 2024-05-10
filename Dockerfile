# Use the official Python image (slim version)
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Copy requirements first to leverage Docker caching for unchanged dependencies
COPY requirements.txt .

# Install dependencies with no cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application files
COPY main.py .

# Set the default command
CMD ["python", "main.py"]
