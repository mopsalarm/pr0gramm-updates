FROM python:3.7-rc-alpine
MAINTAINER Mopsalarm

EXPOSE 8080

COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY . /app

WORKDIR /app

CMD ["python3", "-m", "bottle", "-s", "cherrypy", "-b", "0.0.0.0:8080", "main"]
