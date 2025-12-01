# Example ML Project

This is an example machine learning project for image classification.

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Training

Train the model using the default configuration:

```bash
python train.py --epochs 100 --lr 0.001 --batch-size 32
```

Or use a config file:

```bash
python train.py --config configs/train_config.yaml
```

### Inference

Run inference on test data:

```bash
python inference.py --checkpoint checkpoints/best_model.pt --input data/test/
```

## Model Architecture

We use a ResNet-50 architecture pretrained on ImageNet.

## Dataset

Download the dataset from [link] and place it in the `data/` directory.

## Results

Our model achieves 95% accuracy on the test set.
