FROM node:22-alpine
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY server.js .
COPY lib/ ./lib/
ENV DISPATCHER_PORT=8800
EXPOSE 8800
CMD ["node", "server.js"]
