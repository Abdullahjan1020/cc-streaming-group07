FROM python:3.12-slim AS protocol-generator

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v1.3.0 --recurse-submodules \
        https://github.com/apache/skywalking-python.git /tmp/skywalking-python \
    && test "$(git -C /tmp/skywalking-python rev-parse HEAD)" = "1bd4692f927a4c6156bc25d18d36d9cba76405df" \
    && test "$(git -C /tmp/skywalking-python/protocol rev-parse HEAD)" = "b5f6ebe281b96d89968959f55baa3d9aa1bfecee" \
    && python -m pip install --no-cache-dir "grpcio-tools~=1.83.0" packaging \
    && cd /tmp/skywalking-python \
    && python tools/grpc_code_gen.py \
    && test -f skywalking/protocol/language_agent/Tracing_pb2.py \
    && chmod -R a+rX skywalking/protocol

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=protocol-generator --chown=0:0 \
    /tmp/skywalking-python/skywalking/protocol \
    /usr/local/lib/python3.12/site-packages/skywalking/protocol

COPY app.py .

RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid appgroup --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R 10001:10001 /app

USER 10001:10001

RUN python -c "import skywalking.agent.protocol.grpc, skywalking.client.grpc, skywalking.agent.protocol.grpc_aio, skywalking.client.grpc_aio"

EXPOSE 8003
CMD ["sw-python", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8003"]
