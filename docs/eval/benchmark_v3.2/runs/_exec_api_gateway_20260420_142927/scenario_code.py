import logging
import time
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.config_registry = {
            "v1_endpoint": {
                "proxy_host": "gateway-internal-01",
                "header_alias": "X-Routing-Token"
            },
            "v2_endpoint": {
                "proxy_host": "gateway-internal-02",
                "header_alias": "X-Auth-Identifier"
            }
        }

    @trace
    def get_gateway_config(self, endpoint_id):
        self.logger.info(f"Fetching routing configuration for: {endpoint_id}")
        self.logger.debug("Connecting to distributed-config-store")
        # locate metadata for the specified endpoint
        metadata = self.config_registry.get(endpoint_id)
        if metadata:
            self.logger.info(f"Metadata mapping successful for host: {metadata.get('proxy_host')}")
        return metadata

    @trace
    def enrich_request_headers(self, raw_headers, config):
        self.logger.info("Enriching request headers with internal metadata")
        # map security context to the specific alias defined in config
        auth_key = config.get("auth_header")
        enriched = raw_headers.copy()
        enriched[auth_key] = "SECURE_SESSION_TOKEN_8821"
        
        self.logger.info(f"Header enrichment complete. Total keys: {len(enriched)}")
        return enriched

    @trace
    def validate_ip_restriction(self, source_ip):
        self.logger.debug(f"Checking CIDR allow-list for IP: {source_ip}")
        # simulate complex IP validation logic
        time.sleep(0.02)
        self.logger.info("IP validation passed for segment-12")
        return True

    @trace
    def record_traffic_telemetry(self):
        self.logger.debug("Streaming traffic metrics to analytics-collector")
        self.logger.debug("Buffer status: 12% capacity")

    @trace
    def sign_payload(self, headers):
        self.logger.info("Generating cryptographic signature for outgoing headers")
        self.executor.submit(self.record_traffic_telemetry)
        
        # normalize all header keys to lowercase for canonical signing
        normalized_keys = [k.lower() for k in headers.keys()]
        
        self.logger.info(f"Payload signed with {len(normalized_keys)} headers")
        return True

    @trace
    def run(self):
        endpoint = "v1_endpoint"
        source_ip = "192.168.1.45"
        initial_headers = {"Content-Type": "application/json"}
        
        self.logger.info(f"Processing inbound request for {endpoint}")
        self.executor.submit(self.record_traffic_telemetry)

        # hop 1: get config (contains wrong key 'header_alias' instead of 'auth_header')
        config = self.get_gateway_config(endpoint)
        
        # noise: security check
        self.validate_ip_restriction(source_ip)
        
        # hop 2: enrich headers (None becomes a key in the dict)
        enriched_headers = self.enrich_request_headers(initial_headers, config)
        
        # hop 3: signing (AttributeError: 'NoneType' object has no attribute 'lower')
        self.logger.info("Initiating secure dispatch")
        success = self.sign_payload(enriched_headers)
        
        self.logger.info(f"Request successfully dispatched: {success}")
        self.executor.shutdown(wait=False)