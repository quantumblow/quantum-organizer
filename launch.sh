docker run --rm -p 8080:8080 \
  -v /workspace/personal/videos:/data \
  -v qorg-state:/state \
  quantum-organizer:dev
