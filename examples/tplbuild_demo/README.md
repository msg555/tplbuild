## Tplbuild Demo

This is the demo project used in the video linked in the repo README. See

[![Tplbuild Demo
Video](https://img.youtube.com/vi/HDiyABr8Adw/0.jpg)](https://www.youtube.com/watch?v=HDiyABr8Adw "Tplbuild Demo")

The Dockerfile and codebase was kept fairly simple for demonstration purposes.

## Build and launch the service


```sh
tplbuild build
docker-compose up -d
```


## Send test queries

```sh
# Post a new message
curl -H 'Content-Type: application/json' \
     -d '{"message":"hello world","author":"msg555"}' \
     localhost:8080/message
```

```sh
# Check the messages
curl localhost:8080/message
```
