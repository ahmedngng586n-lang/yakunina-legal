FROM python:3.13-slim
WORKDIR /app
COPY dist ./dist
COPY server ./server
RUN mkdir /app/private && useradd --system legal && chown legal /app/private
USER legal
EXPOSE 9137
CMD ["python", "-u", "server/server.py", "--host", "0.0.0.0", "--port", "9137"]
