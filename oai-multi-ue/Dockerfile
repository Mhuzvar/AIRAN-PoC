FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LD_LIBRARY_PATH=/opt/oai/lib

RUN apt-get update && \
    apt-get install -y \
        tcpdump \
        iperf3 \
        libssl3 \
        libstdc++6 \
        iproute2 \
        iputils-ping \
        procps \
        net-tools \
        kmod \
        ca-certificates \
        && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/oai/lib

COPY nr-uesoftmodem /opt/oai/nr-uesoftmodem
COPY libparams_libconfig.so /opt/oai/lib/libparams_libconfig.so
COPY libconfig.so.9.2.0 /opt/oai/lib/libconfig.so.9.2.0
COPY libldpc.so /opt/oai/lib/libldpc.so
COPY libdfts.so /opt/oai/lib/libdfts.so
COPY librfsimulator.so /opt/oai/lib/librfsimulator.so

RUN ln -s libconfig.so.9.2.0 /opt/oai/lib/libconfig.so.9

RUN chmod +x /opt/oai/nr-uesoftmodem

WORKDIR /opt/oai

CMD ["/opt/oai/nr-uesoftmodem"]
