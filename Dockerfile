# Use official Python image as base
FROM python:3.11-slim
 
# Set working directory
WORKDIR /app
 
# Copy project files into the container
COPY . /app
 
# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    default-libmysqlclient-dev \
&& rm -rf /var/lib/apt/lists/*
 
# Install Python dependencies including fpdf
RUN pip install --upgrade pip
RUN pip install flask pymysql fpdf
 
# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV PYTHONUNBUFFERED=1
 
# Expose the port Flask runs on
EXPOSE 5000
 
# Run the Flask application
CMD ["flask", "run"]