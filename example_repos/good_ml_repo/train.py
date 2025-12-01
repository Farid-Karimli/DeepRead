"""
Training script for ML model.
"""
import argparse
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader


def train(args):
    # Setup model
    model = create_model(args.model_name)

    # Setup optimizer and loss
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    # Setup dataloader
    train_loader = DataLoader(dataset, batch_size=args.batch_size)

    # Training loop
    for epoch in range(args.epochs):
        for batch_idx, (data, target) in enumerate(train_loader):
            optimizer.zero_grad()
            output = model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

            if batch_idx % args.log_interval == 0:
                print(f'Epoch: {epoch}, Loss: {loss.item()}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--model-name', type=str, default='resnet50')
    parser.add_argument('--log-interval', type=int, default=100)
    args = parser.parse_args()

    train(args)
