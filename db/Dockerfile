# db/Dockerfile
FROM pgvector/pgvector:pg16

# 이 30권짜리 초기화 SQL 파일은 로컬 볼륨 공간이 텅 비어있을 때 자동으로 전 자동 적재됩니다 [1.1.2].
COPY bookfit_init.sql /docker-entrypoint-initdb.d/