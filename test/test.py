import os
import json
import boto3
import logging
import argparse
import requests
from pathlib import Path
import base64
import albumentations as A
from PIL import Image
import numpy as np
import io

logger = logging.getLogger(__name__)
api_client = boto3.client('apigatewayv2', region_name="ap-south-1")


def get_api_url(api_name):
    list_apis = api_client.get_apis()['Items']
    filtered_apis = [api for api in list_apis if api["Name"] == api_name]
    api_url = filtered_apis[0]['ApiEndpoint']
    return api_url


def test_api(name, url, image_path):
    transforms = A.Compose(
                [
                    A.GaussNoise(p=0.2),
                    A.OneOf(
                        [
                            A.MotionBlur(p=0.2),
                            A.MedianBlur(blur_limit=3, p=0.1),
                            A.Blur(blur_limit=3, p=0.1),
                        ],
                        p=0.2,
                    ),
                ]
            ) 

    try:
        for file in image_path.glob("*/*.jpg"):
            print(f"{file=}")

            image = Image.open(file)
            image = np.array(image)
            augmented_image = transforms(image=image)["image"]

            buf = io.BytesIO()
            aug_image = Image.fromarray(augmented_image)
            aug_image.save(buf, format="JPEG")
            
            ext = file.name.split('.')[-1]
            prefix = f'data:image/{ext};base64,'
            base64_data = prefix + base64.b64encode(buf.getvalue()).decode('utf-8')

            payload = json.dumps({"body": [base64_data]})
            headers = {"content-type": "application/json"}

            response = requests.request("POST", url, json=payload, headers=headers)
            response.raise_for_status()  # if status !=200 raise exception

            prediction = response.json()[0]
            prediction_sorted = sorted(prediction.items(), key=lambda x:x[1], reverse=True)
            print(prediction_sorted)

            assert prediction_sorted[0][0] == file.parent.stem
        
        return "Success"

    except requests.exceptions.HTTPError as err:
        raise SystemExit(err)

    except AssertionError as err:
        logger.debug("Assert failed")
        raise SystemExit(err)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", type=str, default=os.environ.get("LOGLEVEL", "INFO").upper())
    parser.add_argument("--import-build-config", type=str, required=True)
    parser.add_argument("--export-test-results", type=str, required=True)
    args, _ = parser.parse_known_args()

    # Configure logging to output the line number and message
    log_format = "%(levelname)s: [%(filename)s:%(lineno)s] %(message)s"
    logging.basicConfig(format=log_format, level=args.log_level)

    # Load the build config
    with open(args.import_build_config, "r") as f:
        config = json.load(f)

    # Get the api name from sagemaker project name
    api_name = "{}-{}".format(config["Parameters"]["SageMakerProjectName"], config["Parameters"]["StageName"])

    api_url = get_api_url(api_name)

    # send a test data point to the api and verifying the response status code
    resource_path = Path("test/resources/intel-scene")
    response = test_api(api_name, api_url, resource_path)

    results = {
            'api_name': api_name,
            'api_url': api_url,
            'response': response
        }

    # Print results and write to file
    logger.debug(json.dumps(results, indent=4))
    with open(args.export_test_results, "w") as f:
        json.dump(results, f, indent=4)