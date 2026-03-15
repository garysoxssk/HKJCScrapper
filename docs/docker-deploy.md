docker build -t prod/hkjc-scrapper-repo . && \
docker tag prod/hkjc-scrapper-repo:latest 077527764894.dkr.ecr.ap-southeast-2.amazonaws.com/prod/hkjc-scrapper-repo:latest && \
docker push 077527764894.dkr.ecr.ap-southeast-2.amazonaws.com/prod/hkjc-scrapper-repo:latest