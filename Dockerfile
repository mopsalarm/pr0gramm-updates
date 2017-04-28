FROM python:3.6-alpine
MAINTAINER Mopsalarm

EXPOSE 8080

COPY . /app
RUN pip install -r /app/requirements.txt

WORKDIR /app

CMD ["python3", "-m", "bottle", "-s", "cherrypy", "-b", "0.0.0.0:8080", "main"]
