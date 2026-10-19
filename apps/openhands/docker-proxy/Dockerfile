# Docker Socket Proxy - exposes /var/run/docker.sock over TCP
# This allows agent-server containers to use Docker without direct socket mount
FROM alpine:3.20
RUN apk add --no-cache socat
EXPOSE 2375
ENTRYPOINT ["socat", "TCP-LISTEN:2375,reuseaddr,fork", "UNIX-CONNECT:/var/run/docker.sock"]
