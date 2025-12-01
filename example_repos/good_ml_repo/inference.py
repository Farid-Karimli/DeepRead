"""
Inference script for running predictions.
"""
import torch
import argparse


def load_model(checkpoint_path):
    """Load trained model from checkpoint."""
    model = torch.load(checkpoint_path)
    model.eval()
    return model


def predict(model, input_data):
    """Run inference on input data."""
    with torch.no_grad():
        output = model(input_data)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', type=str, required=True)
    parser.add_argument('--input', type=str, required=True)
    args = parser.parse_args()

    model = load_model(args.checkpoint)
    predictions = predict(model, args.input)
    print(f'Predictions: {predictions}')
